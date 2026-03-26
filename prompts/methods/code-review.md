## Code Review Checklist (Mandatory for S5)

### Two-Stage Review Process
**Stage 1: Spec Compliance** (do first)
- Does implementation match ALL requirements from the spec?
- Any requirements skipped or missed?
- Any extra features added that weren't requested?
- Any misinterpretation of requirements?

**Stage 2: Code Quality** (only after Stage 1 passes)
- Proper error handling at every level
- Type safety and input validation at boundaries
- No hardcoded values (use constants/config)
- Functions < 50 lines, files < 800 lines
- Immutable patterns (no mutation)
- Security: no injection, no XSS, no hardcoded secrets

### CRITICAL: Do NOT Trust Agent Reports
- Read the actual code, not the summary
- Compare implementation to requirements line by line
- Check for missing pieces claimed as implemented
- Look for over-engineering not mentioned

### Issue Severity
- **CRITICAL** — Security vulnerability, data loss risk, crash → must fix
- **HIGH** — Incorrect behavior, missing requirement → must fix
- **MEDIUM** — Poor performance, weak error handling → should fix
- **LOW** — Style, naming, documentation → nice to fix
