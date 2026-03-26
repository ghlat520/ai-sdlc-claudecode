"""Tests for ai_sdlc_claudecode.summarizer — StageSummarizer."""

import json
from pathlib import Path

import pytest

from ai_sdlc_claudecode.summarizer import StageSummarizer, CONTEXT_STRATEGY


@pytest.fixture
def summarizer() -> StageSummarizer:
    return StageSummarizer()


@pytest.fixture
def upstream_dir(tmp_path: Path) -> Path:
    """Create a fake upstream output directory with sample stage outputs."""
    # S1 - requirements
    s1_dir = tmp_path / "S1-requirements"
    s1_dir.mkdir()
    (s1_dir / "output.json").write_text(json.dumps({
        "stage_id": "S1",
        "stage_name": "Requirements",
        "summary": "User authentication feature",
        "acceptance_criteria": ["Login with email", "Password reset", "2FA support"],
        "user_stories": [
            {"title": "As a user I want to log in", "acceptance_criteria": ["Email login works"]},
        ],
    }, ensure_ascii=False))

    # S2 - architecture
    s2_dir = tmp_path / "S2-architecture"
    s2_dir.mkdir()
    (s2_dir / "output.json").write_text(json.dumps({
        "stage_id": "S2",
        "stage_name": "Architecture",
        "summary": "Microservice auth design",
        "api_contracts": [
            {"endpoint": "/api/login", "method": "POST", "description": "User login"},
            {"endpoint": "/api/reset", "method": "POST", "description": "Password reset"},
        ],
        "technical_decisions": ["Use JWT tokens", "Redis session store"],
        "data_model": {"users": {"columns": ["id", "email", "password_hash"]}},
    }, ensure_ascii=False))

    # S3 - backend
    s3_dir = tmp_path / "S3-backend"
    s3_dir.mkdir()
    (s3_dir / "output.json").write_text(json.dumps({
        "stage_id": "S3",
        "stage_name": "Backend",
        "summary": "Auth service implemented",
        "files_changed": [
            {"path": "src/auth/login.ts", "action": "created", "methods": ["handleLogin", "validateCredentials"]},
            {"path": "src/auth/reset.ts", "action": "created", "methods": ["handleReset"]},
        ],
    }, ensure_ascii=False))

    # S3b - frontend
    s3b_dir = tmp_path / "S3b-frontend"
    s3b_dir.mkdir()
    (s3b_dir / "output.json").write_text(json.dumps({
        "stage_id": "S3b",
        "stage_name": "Frontend",
        "summary": "Login UI implemented",
        "files_changed": [
            {"path": "src/pages/Login.vue", "action": "created"},
            {"path": "src/pages/Reset.vue", "action": "created"},
        ],
    }, ensure_ascii=False))

    # S4 - testing
    s4_dir = tmp_path / "S4-testing"
    s4_dir.mkdir()
    (s4_dir / "output.json").write_text(json.dumps({
        "stage_id": "S4",
        "stage_name": "Testing",
        "test_count": 15,
        "pass_count": 14,
        "fail_count": 1,
        "coverage": "85%",
        "summary": "Unit tests for auth",
        "failures": ["test_2fa_edge_case"],
    }, ensure_ascii=False))

    # S5 - review
    s5_dir = tmp_path / "S5-review"
    s5_dir.mkdir()
    (s5_dir / "output.json").write_text(json.dumps({
        "stage_id": "S5",
        "stage_name": "Review",
        "summary": "Code review complete",
        "issues": [
            {"severity": "high", "description": "Missing input validation"},
            {"severity": "low", "description": "Typo in comment"},
        ],
    }, ensure_ascii=False))

    return tmp_path


class TestBuildContext:
    def test_s2_gets_prd_essentials_from_s1(self, summarizer: StageSummarizer, upstream_dir: Path) -> None:
        ctx = summarizer.build_context("S2", upstream_dir)
        assert "S1" in ctx
        assert "Login with email" in ctx
        # Should use prd_essentials extractor, not full dump
        assert "prd_essentials" in ctx

    def test_s3_gets_criteria_and_arch_essentials(self, summarizer: StageSummarizer, upstream_dir: Path) -> None:
        ctx = summarizer.build_context("S3", upstream_dir)
        assert "acceptance_criteria" in ctx.lower() or "Login with email" in ctx
        assert "/api/login" in ctx or "arch_essentials" in ctx

    def test_s4_gets_criteria_and_signatures(self, summarizer: StageSummarizer, upstream_dir: Path) -> None:
        ctx = summarizer.build_context("S4", upstream_dir)
        assert "Login with email" in ctx or "acceptance_criteria" in ctx.lower()
        assert "login.ts" in ctx or "file_signatures" in ctx.lower()

    def test_s5_gets_change_summary_and_tests(self, summarizer: StageSummarizer, upstream_dir: Path) -> None:
        ctx = summarizer.build_context("S5", upstream_dir)
        # Should have change info from S3 and test results from S4
        assert "login.ts" in ctx or "backend" in ctx.lower() or "S3" in ctx

    def test_unknown_stage_fallback(self, summarizer: StageSummarizer, upstream_dir: Path) -> None:
        ctx = summarizer.build_context("S99", upstream_dir)
        # Should use fallback and include something
        assert len(ctx) > 0

    def test_missing_upstream_returns_empty(self, summarizer: StageSummarizer, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        ctx = summarizer.build_context("S3", empty_dir)
        assert ctx == ""

    def test_context_within_budget(self, summarizer: StageSummarizer, upstream_dir: Path) -> None:
        for stage_id, strategies in CONTEXT_STRATEGY.items():
            ctx = summarizer.build_context(stage_id, upstream_dir)
            total_budget = sum(max_chars for _, _, max_chars in strategies)
            # Context should not vastly exceed the budget (allow for headers)
            assert len(ctx) <= total_budget + 1000, f"{stage_id} context exceeds budget"


class TestSummarizeOutput:
    def test_requirements_summary(self, summarizer: StageSummarizer) -> None:
        output = {
            "stage_id": "S1",
            "summary": "Auth feature",
            "acceptance_criteria": ["Login", "Reset"],
            "user_stories": [{"title": "Login story"}],
        }
        result = summarizer.summarize_output("S1", output)
        assert result["stage_id"] == "S1"
        assert result["acceptance_criteria"] == ["Login", "Reset"]
        assert result["user_stories_count"] == 1

    def test_architecture_summary(self, summarizer: StageSummarizer) -> None:
        output = {
            "stage_id": "S2",
            "api_contracts": [{"endpoint": "/api/login", "method": "POST", "description": "Login"}],
            "technical_decisions": ["JWT", "Redis"],
        }
        result = summarizer.summarize_output("S2", output)
        assert len(result["interfaces"]) == 1
        assert result["tech_decisions"] == ["JWT", "Redis"]

    def test_backend_summary(self, summarizer: StageSummarizer) -> None:
        output = {
            "stage_id": "S3",
            "files_changed": [
                {"path": "src/a.ts", "action": "created", "methods": ["foo", "bar"]},
            ],
        }
        result = summarizer.summarize_output("S3", output)
        assert len(result["files"]) == 1
        assert result["files_changed_count"] == 1

    def test_testing_summary(self, summarizer: StageSummarizer) -> None:
        output = {"stage_id": "S4", "test_count": 10, "pass_count": 9, "coverage": "80%"}
        result = summarizer.summarize_output("S4", output)
        assert result["test_count"] == 10
        assert result["coverage"] == "80%"

    def test_review_summary(self, summarizer: StageSummarizer) -> None:
        output = {
            "stage_id": "S5",
            "issues": [
                {"severity": "critical", "description": "SQL injection"},
                {"severity": "low", "description": "Typo"},
            ],
        }
        result = summarizer.summarize_output("S5", output)
        assert result["issues_count"] == 2
        assert len(result["critical_issues"]) == 1


class TestExtractors:
    def test_acceptance_criteria_direct(self, summarizer: StageSummarizer) -> None:
        data = {"acceptance_criteria": ["A", "B", "C"]}
        assert summarizer.extract_acceptance_criteria(data) == ["A", "B", "C"]

    def test_acceptance_criteria_from_stories(self, summarizer: StageSummarizer) -> None:
        data = {
            "user_stories": [
                {"acceptance_criteria": ["X", "Y"]},
                {"acceptance_criteria": "Z"},
            ]
        }
        result = summarizer.extract_acceptance_criteria(data)
        assert "X" in result and "Y" in result and "Z" in result

    def test_interfaces_from_contracts(self, summarizer: StageSummarizer) -> None:
        data = {"api_contracts": [{"endpoint": "/api/test", "method": "GET", "description": "Test"}]}
        result = summarizer.extract_interfaces(data)
        assert len(result) == 1
        assert result[0]["endpoint"] == "/api/test"

    def test_file_signatures_dict(self, summarizer: StageSummarizer) -> None:
        data = {"files_changed": [{"path": "a.ts", "methods": ["foo"]}]}
        result = summarizer.extract_file_signatures(data)
        assert result[0]["path"] == "a.ts"
        assert result[0]["methods"] == ["foo"]

    def test_file_signatures_string(self, summarizer: StageSummarizer) -> None:
        data = {"files_changed": ["a.ts", "b.ts"]}
        result = summarizer.extract_file_signatures(data)
        assert len(result) == 2
        assert result[0]["path"] == "a.ts"


class TestPrdEssentials:
    def test_extracts_title_summary_reqs(self, summarizer: StageSummarizer) -> None:
        data = {
            "prd": {
                "title": "My Feature",
                "summary": "A great feature",
                "functional_requirements": [
                    {"id": "FR-1", "description": "Do X", "priority": "high"},
                    {"id": "FR-2", "description": "Do Y", "priority": "low"},
                ],
            },
            "acceptance_criteria": ["AC-1", "AC-2"],
        }
        result = summarizer._extract_prd_essentials(data)
        assert "My Feature" in result
        assert "FR-1" in result
        assert "Do X" in result
        assert "AC-1" in result

    def test_handles_flat_structure(self, summarizer: StageSummarizer) -> None:
        data = {
            "title": "Flat Title",
            "summary": "Flat summary",
            "functional_requirements": [{"id": "FR-A", "description": "Flat req", "priority": "med"}],
        }
        result = summarizer._extract_prd_essentials(data)
        assert "Flat Title" in result
        assert "FR-A" in result

    def test_truncates_long_descriptions(self, summarizer: StageSummarizer) -> None:
        data = {
            "prd": {
                "functional_requirements": [
                    {"id": "FR-1", "description": "X" * 500, "priority": "high"},
                ],
            }
        }
        result = summarizer._extract_prd_essentials(data)
        # Description should be truncated to 200 chars
        assert len(result) < 400


class TestArchEssentials:
    def test_extracts_modules_tables_endpoints(self, summarizer: StageSummarizer) -> None:
        data = {
            "architecture": {
                "overview": "Service arch",
                "modules": [{"name": "auth", "description": "Auth module", "key_files": ["auth.ts"]}],
                "database_design": {
                    "tables": [{"name": "users", "columns": [{"name": "id"}, {"name": "email"}]}]
                },
                "api_design": {
                    "endpoints": [{"method": "POST", "path": "/login", "description": "Login"}]
                },
                "technical_decisions": ["Use JWT"],
            }
        }
        result = summarizer._extract_arch_essentials(data)
        assert "auth" in result
        assert "users" in result
        assert "POST /login" in result
        assert "JWT" in result

    def test_handles_flat_arch(self, summarizer: StageSummarizer) -> None:
        data = {
            "overview": "Flat overview",
            "modules": [{"name": "core", "description": "Core module"}],
        }
        result = summarizer._extract_arch_essentials(data)
        assert "Flat overview" in result
        assert "core" in result

    def test_handles_list_api_contracts(self, summarizer: StageSummarizer) -> None:
        data = {
            "architecture": {
                "api_contracts": [
                    {"method": "GET", "path": "/api/items", "description": "List items"},
                ],
            }
        }
        result = summarizer._extract_arch_essentials(data)
        # api_contracts is a list, should still be handled
        assert len(result) >= 0  # Should not crash


class TestStrategyTable:
    def test_all_stages_have_budgets(self) -> None:
        """Every strategy entry must have a positive max_chars."""
        for stage_id, strategies in CONTEXT_STRATEGY.items():
            for source_id, extractor, max_chars in strategies:
                assert max_chars > 0, f"{stage_id} strategy for {source_id} has non-positive budget"
                assert extractor, f"{stage_id} strategy for {source_id} has empty extractor"
