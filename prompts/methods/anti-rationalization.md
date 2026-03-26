## Anti-Rationalization Guards (All Stages)

### Workaround Detection
| Dangerous Action | Why It's Wrong | Correct Action |
|------------------|---------------|----------------|
| `--force` / `--skip-checks` | Bypasses safety gates | Find why the check fails |
| catch exception then ignore | Hides real errors | Find why exception is thrown |
| "Use mock data for now" | Defers real integration | Wire up real data source |
| Retry same command hoping it works | Gambling, not engineering | Diagnose why it failed |
| "Will fix later" | It won't get fixed | Fix now or file tracked issue |
| Hardcode values to pass test | Test theater | Fix the implementation |

### Quality Shortcuts to Reject
- Generating placeholder/stub code instead of real implementation
- Using setTimeout/sleep instead of proper async handling
- Catching all exceptions with empty handler
- Skipping edge cases "to save time"
- Using `any` type to avoid type errors

### <HARD-GATE>
If you find yourself rationalizing why a shortcut is acceptable, STOP.
That rationalization IS the signal that you're about to produce low-quality output.
Go back and do it properly.
</HARD-GATE>

### Status Protocol
Report your actual status honestly:
- **DONE** — All requirements met, tests pass, verified
- **DONE_WITH_CONCERNS** — Completed but have doubts (list them)
- **BLOCKED** — Cannot complete (explain why, what you tried)
- **NEEDS_CONTEXT** — Missing information to proceed (specify what)

**Never report DONE when the honest status is DONE_WITH_CONCERNS or BLOCKED.**
