"""Intelligent Context Summarizer — stage-aware upstream context trimming.

Replaces the blunt 50000-char truncation with a strategy table that gives
each downstream stage exactly the upstream slices it needs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


# --- Strategy Table ---
# target_stage_id → list of (upstream_stage_id, extractor_name, max_chars)
# Budget targets: S1 output ~3K, S2 output ~5K to downstream, summaries ~2K each.
# Previous budgets (30K, 12K, 10K) caused 150K+ token prompts. Reduced by ~70%.
CONTEXT_STRATEGY: dict[str, list[tuple[str, str, int]]] = {
    "S2": [("S1", "prd_essentials", 8000)],
    "S3": [("S1", "acceptance_criteria", 3000), ("S2", "arch_essentials", 5000)],
    "S3b": [("S1", "acceptance_criteria", 3000), ("S2", "arch_essentials", 5000)],
    "S4": [("S1", "acceptance_criteria", 2000), ("S3", "file_signatures", 5000)],
    "S4b": [("S2", "arch_essentials", 3000), ("S3", "file_signatures", 5000)],
    "S4c": [("S1", "acceptance_criteria", 2000), ("S3", "file_signatures", 3000), ("S3b", "file_signatures", 3000)],
    "S5": [("S3", "change_summary", 4000), ("S3b", "change_summary", 2000), ("S4", "test_results", 2000)],
    "S6": [("S2", "summary", 2000), ("S5", "summary", 2000)],
    "S7": [("S2", "summary", 2000), ("S6", "summary", 2000)],
    "S8": [("S1", "summary", 2000), ("S2", "summary", 2000), ("S3", "summary", 2000)],
    "S9": [("S1", "acceptance_criteria", 2000), ("S2", "summary", 2000), ("S3", "summary", 2000)],
    "S10": [("S7", "summary", 2000), ("S8", "summary", 2000), ("S9", "summary", 2000)],
}


class StageSummarizer:
    """Builds context for downstream stages using strategy-based extraction."""

    def build_context(self, target_stage_id: str, upstream_dir: str | Path) -> str:
        """Build trimmed context for a target stage from upstream outputs.

        Args:
            target_stage_id: The stage that needs context (e.g. "S3")
            upstream_dir: Directory containing stage output subdirs

        Returns:
            Combined upstream context string within budget
        """
        upstream_dir = Path(upstream_dir)
        strategies = CONTEXT_STRATEGY.get(target_stage_id)

        if not strategies:
            # Fallback: collect all upstream outputs with reduced budget
            return self._fallback_context(upstream_dir, max_chars=8000)

        parts: list[str] = []
        for source_id, extractor_name, max_chars in strategies:
            output_data = self._load_stage_output(upstream_dir, source_id)
            if output_data is None:
                continue

            extracted = self._extract(output_data, extractor_name, max_chars)
            if extracted:
                parts.append(f"## {source_id} ({extractor_name})\n{extracted}")

        return "\n\n".join(parts) if parts else ""

    def summarize_output(self, stage_id: str, full_output: dict) -> dict:
        """Generate a compact summary of a stage's output for storage.

        Returns a dict with key fields only, suitable for {stage_id}-summary.json.
        """
        summary: dict = {"stage_id": stage_id}

        # Extract commonly useful fields
        for key in ("stage_id", "stage_name", "status", "summary", "key_decisions"):
            if key in full_output:
                summary[key] = full_output[key]

        # Stage-specific extractions
        if stage_id in ("S1",):
            summary["acceptance_criteria"] = self.extract_acceptance_criteria(full_output)
            summary["user_stories_count"] = len(full_output.get("user_stories", []))

        if stage_id in ("S2",):
            summary["interfaces"] = self.extract_interfaces(full_output)
            summary["tech_decisions"] = full_output.get("technical_decisions", [])[:5]

        if stage_id in ("S3", "S3b"):
            summary["files"] = self.extract_file_signatures(full_output)
            summary["files_changed_count"] = len(full_output.get("files_changed", []))

        if stage_id in ("S4", "S4b", "S4c"):
            summary["test_count"] = full_output.get("test_count", 0)
            summary["pass_count"] = full_output.get("pass_count", 0)
            summary["coverage"] = full_output.get("coverage", "unknown")

        if stage_id in ("S5",):
            summary["issues_count"] = len(full_output.get("issues", []))
            summary["critical_issues"] = [
                i for i in full_output.get("issues", [])
                if isinstance(i, dict) and i.get("severity") in ("critical", "high")
            ][:5]

        return summary

    def extract_acceptance_criteria(self, req_output: dict) -> list[str]:
        """Extract acceptance criteria from requirements output."""
        criteria = req_output.get("acceptance_criteria", [])
        if criteria:
            return criteria[:20]

        # Try nested in user_stories
        all_criteria: list[str] = []
        for story in req_output.get("user_stories", []):
            if isinstance(story, dict):
                ac = story.get("acceptance_criteria", [])
                if isinstance(ac, list):
                    all_criteria.extend(ac)
                elif isinstance(ac, str):
                    all_criteria.append(ac)
        return all_criteria[:20]

    def extract_interfaces(self, arch_output: dict) -> list[dict]:
        """Extract API/interface definitions from architecture output."""
        interfaces: list[dict] = []

        # Try api_contracts
        for contract in arch_output.get("api_contracts", []):
            if isinstance(contract, dict):
                interfaces.append({
                    "endpoint": contract.get("endpoint", ""),
                    "method": contract.get("method", ""),
                    "description": contract.get("description", ""),
                })

        # Try interfaces key
        for iface in arch_output.get("interfaces", []):
            if isinstance(iface, dict):
                interfaces.append({
                    "name": iface.get("name", ""),
                    "methods": iface.get("methods", [])[:5],
                })

        return interfaces[:20]

    def extract_file_signatures(self, dev_output: dict) -> list[dict]:
        """Extract file list + method signatures from dev output."""
        signatures: list[dict] = []

        for f in dev_output.get("files_changed", []):
            if isinstance(f, dict):
                sig = {"path": f.get("path", ""), "action": f.get("action", "modified")}
                methods = f.get("methods", f.get("functions", []))
                if methods:
                    sig["methods"] = [m if isinstance(m, str) else m.get("name", "") for m in methods[:10]]
                signatures.append(sig)
            elif isinstance(f, str):
                signatures.append({"path": f, "action": "modified"})

        return signatures[:30]

    # --- Private extractors ---

    def _extract(self, data: dict, extractor_name: str, max_chars: int) -> str:
        """Run a named extractor and truncate to budget."""
        if extractor_name == "full":
            text = json.dumps(data, indent=2, ensure_ascii=False)
        elif extractor_name == "prd_essentials":
            text = self._extract_prd_essentials(data)
        elif extractor_name == "arch_essentials":
            text = self._extract_arch_essentials(data)
        elif extractor_name == "summary":
            text = self._extract_summary(data)
        elif extractor_name == "acceptance_criteria":
            criteria = self.extract_acceptance_criteria(data)
            text = "\n".join(f"- {c}" for c in criteria) if criteria else json.dumps(data, ensure_ascii=False)
        elif extractor_name == "interfaces_and_decisions":
            text = self._extract_interfaces_and_decisions(data)
        elif extractor_name == "file_signatures":
            sigs = self.extract_file_signatures(data)
            text = json.dumps(sigs, indent=2, ensure_ascii=False) if sigs else ""
        elif extractor_name == "change_summary":
            text = self._extract_change_summary(data)
        elif extractor_name == "test_results":
            text = self._extract_test_results(data)
        else:
            text = json.dumps(data, indent=2, ensure_ascii=False)

        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [TRIMMED to {max_chars} chars]"
        return text

    def _extract_prd_essentials(self, data: dict) -> str:
        """Extract essential PRD fields from S1 requirements output.

        Keeps: title, summary, functional requirements (id + short description +
        priority), and acceptance criteria.  Drops verbose fields like
        background, non-functional details, and full user story narratives.
        """
        parts: list[str] = []

        # Title & summary
        prd = data.get("prd", data)
        title = prd.get("title", data.get("title", ""))
        if title:
            parts.append(f"Title: {title}")
        summary = prd.get("summary", data.get("summary", ""))
        if summary:
            parts.append(f"Summary: {str(summary)[:500]}")

        # Functional requirements — id + description (truncated) + priority
        func_reqs = prd.get("functional_requirements", data.get("functional_requirements", []))
        if func_reqs:
            req_lines: list[str] = []
            for fr in func_reqs[:20]:
                if isinstance(fr, dict):
                    fr_id = fr.get("id", "")
                    desc = str(fr.get("description", ""))[:200]
                    prio = fr.get("priority", "")
                    req_lines.append(f"- [{fr_id}] {desc} (priority: {prio})")
                elif isinstance(fr, str):
                    req_lines.append(f"- {fr[:200]}")
            parts.append("### Functional Requirements\n" + "\n".join(req_lines))

        # Acceptance criteria
        criteria = self.extract_acceptance_criteria(data)
        if criteria:
            parts.append("### Acceptance Criteria\n" + "\n".join(f"- {c}" for c in criteria))

        return "\n\n".join(parts) if parts else json.dumps(data, ensure_ascii=False)[:3000]

    def _extract_arch_essentials(self, data: dict) -> str:
        """Extract essential architecture fields from S2 output.

        Keeps: overview (truncated), module names + descriptions, database
        table names + columns, and API endpoints.  Drops verbose rationale,
        diagrams, and full implementation notes.
        """
        arch = data.get("architecture", data)
        parts: list[str] = []

        # Overview — short
        overview = arch.get("overview", data.get("overview", ""))
        if overview:
            parts.append(f"Overview: {str(overview)[:500]}")

        # Modules — name + short description + key files
        modules = arch.get("modules", data.get("modules", []))
        if modules:
            mod_lines: list[str] = []
            for m in modules[:15]:
                if isinstance(m, dict):
                    name = m.get("name", "")
                    desc = str(m.get("description", ""))[:150]
                    files = m.get("key_files", [])[:5]
                    line = f"- **{name}**: {desc}"
                    if files:
                        line += f"  files: {', '.join(str(f) for f in files)}"
                    mod_lines.append(line)
            parts.append("### Modules\n" + "\n".join(mod_lines))

        # Database tables — name + columns
        db = arch.get("database_design", arch.get("database_schema", data.get("database_design", {})))
        if isinstance(db, dict):
            tables = db.get("tables", [])
            if tables:
                tbl_lines: list[str] = []
                for t in tables[:20]:
                    if isinstance(t, dict):
                        tname = t.get("name", "")
                        cols = t.get("columns", [])
                        col_names = []
                        for c in cols[:15]:
                            if isinstance(c, dict):
                                col_names.append(c.get("name", str(c)))
                            else:
                                col_names.append(str(c))
                        tbl_lines.append(f"- **{tname}**: {', '.join(col_names)}")
                parts.append("### Database Tables\n" + "\n".join(tbl_lines))

        # API endpoints — path + method
        api = arch.get("api_design", arch.get("api_contracts", data.get("api_design", {})))
        if isinstance(api, dict):
            endpoints = api.get("endpoints", [])
        elif isinstance(api, list):
            endpoints = api
        else:
            endpoints = []
        if endpoints:
            ep_lines: list[str] = []
            for ep in endpoints[:20]:
                if isinstance(ep, dict):
                    method = ep.get("method", "GET")
                    path = ep.get("path", ep.get("endpoint", ""))
                    desc = str(ep.get("description", ""))[:100]
                    ep_lines.append(f"- {method} {path} — {desc}")
            parts.append("### API Endpoints\n" + "\n".join(ep_lines))

        # Technical decisions — short list
        decisions = arch.get("technical_decisions", data.get("technical_decisions", data.get("key_decisions", [])))
        if isinstance(decisions, list) and decisions:
            parts.append("### Tech Decisions\n" + "\n".join(f"- {d}" for d in decisions[:8]))

        return "\n\n".join(parts) if parts else json.dumps(data, ensure_ascii=False)[:3000]

    def _extract_summary(self, data: dict) -> str:
        """Extract summary fields from any stage output."""
        parts: list[str] = []
        for key in ("summary", "stage_name", "key_decisions", "status"):
            val = data.get(key)
            if val:
                if isinstance(val, list):
                    parts.append(f"{key}: " + "; ".join(str(v) for v in val[:5]))
                else:
                    parts.append(f"{key}: {val}")
        return "\n".join(parts) if parts else json.dumps(data, ensure_ascii=False)[:3000]

    def _extract_interfaces_and_decisions(self, data: dict) -> str:
        """Extract interfaces + technical decisions from architecture output."""
        parts: list[str] = []

        interfaces = self.extract_interfaces(data)
        if interfaces:
            parts.append("### Interfaces\n" + json.dumps(interfaces, indent=2, ensure_ascii=False))

        decisions = data.get("technical_decisions", data.get("key_decisions", []))
        if decisions:
            if isinstance(decisions, list):
                parts.append("### Technical Decisions\n" + "\n".join(f"- {d}" for d in decisions[:10]))

        data_model = data.get("data_model", data.get("database_schema", ""))
        if data_model:
            parts.append("### Data Model\n" + (json.dumps(data_model, indent=2, ensure_ascii=False) if isinstance(data_model, (dict, list)) else str(data_model)))

        return "\n\n".join(parts)

    def _extract_change_summary(self, data: dict) -> str:
        """Summarize code changes from dev output."""
        parts: list[str] = []
        files = data.get("files_changed", [])
        if files:
            paths = [f.get("path", f) if isinstance(f, dict) else f for f in files[:20]]
            parts.append("Files changed:\n" + "\n".join(f"- {p}" for p in paths))

        summary = data.get("summary", "")
        if summary:
            parts.append(f"Summary: {summary}")

        return "\n\n".join(parts)

    def _extract_test_results(self, data: dict) -> str:
        """Summarize test results."""
        parts: list[str] = []
        for key in ("test_count", "pass_count", "fail_count", "coverage", "summary"):
            val = data.get(key)
            if val is not None:
                parts.append(f"{key}: {val}")

        failures = data.get("failures", data.get("failed_tests", []))
        if failures:
            parts.append("Failures:\n" + "\n".join(f"- {f}" for f in failures[:5]))

        return "\n".join(parts)

    def _load_stage_output(self, upstream_dir: Path, stage_id: str) -> Optional[dict]:
        """Load a stage's output.json from its directory."""
        # Try common patterns: S3-backend, S1-requirements, etc.
        for subdir in upstream_dir.iterdir() if upstream_dir.exists() else []:
            if subdir.is_dir() and subdir.name.startswith(f"{stage_id}-"):
                output_file = subdir / "output.json"
                if output_file.exists():
                    try:
                        return json.loads(output_file.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        return None

                # Try summary file
                summary_file = subdir / f"{stage_id}-summary.json"
                if summary_file.exists():
                    try:
                        return json.loads(summary_file.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        return None
        return None

    def _fallback_context(self, upstream_dir: Path, max_chars: int = 20000) -> str:
        """Fallback: load all upstream outputs with simple truncation."""
        parts: list[str] = []
        char_count = 0

        if not upstream_dir.exists():
            return ""

        for subdir in sorted(upstream_dir.iterdir()):
            if not subdir.is_dir():
                continue
            output_file = subdir / "output.json"
            if not output_file.exists():
                continue
            try:
                data = output_file.read_text(encoding="utf-8")
                remaining = max_chars - char_count
                if remaining <= 0:
                    break
                if len(data) > remaining:
                    data = data[:remaining] + "\n... [TRIMMED]"
                parts.append(f"## {subdir.name}\n{data}")
                char_count += len(data)
            except OSError:
                continue

        return "\n\n".join(parts)
