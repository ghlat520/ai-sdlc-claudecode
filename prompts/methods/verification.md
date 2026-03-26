## Verification Before Completion (Mandatory)

**Iron Law: NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE**

### The Gate Function
Before claiming ANY status:
1. **IDENTIFY** — What command proves this claim?
2. **RUN** — Execute the FULL command (fresh, complete)
3. **READ** — Full output, check exit code, count failures
4. **VERIFY** — Does output confirm the claim?
5. **ONLY THEN** — Make the claim

### Evidence Requirements
| Claim | Requires | NOT Sufficient |
|-------|----------|----------------|
| Tests pass | Test output: 0 failures | "should pass" |
| Build succeeds | Build command: exit 0 | "linter passed" |
| Bug fixed | Failing test now passes | "code looks correct" |
| Feature complete | All acceptance criteria verified | "I implemented it" |

### Red Flags — STOP
- Using "should", "probably", "seems to"
- Expressing satisfaction before running verification
- About to claim completion without evidence
- Trusting previous run results instead of fresh run

**Claiming work is complete without verification is dishonesty, not efficiency.**

**IMPORTANT: The verification evidence block is IN ADDITION to your main JSON output. You MUST include BOTH:**
1. The complete JSON output (in a ```json code block)
2. The verification evidence block (after the JSON)

---

## Structured Evidence Output (MANDATORY)

After completing verification, you **MUST** include this block in your output.
The pipeline extracts this block automatically — omitting it triggers a warning or rejection.

```
### VERIFICATION_EVIDENCE
| Command | Exit Code | Key Output |
|---------|-----------|------------|
| <actual command you ran> | <exit code> | <key output summary, max 200 chars> |
| <next command> | <exit code> | <summary> |

### VERIFICATION_STATUS: <VERIFIED|UNVERIFIED|PARTIAL>
```

**Rules:**
- List EVERY verification command you actually executed
- Exit code must be the real exit code (0 = success)
- Key Output: include test count, coverage %, error count, or build status
- VERIFICATION_STATUS meanings:
  - `VERIFIED` — all commands ran, all passed
  - `PARTIAL` — some commands ran, not all passed
  - `UNVERIFIED` — no verification commands were executed
