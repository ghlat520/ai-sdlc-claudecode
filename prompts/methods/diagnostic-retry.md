# Diagnostic Retry Methodology

> Injected when a pipeline stage FAILS and is being retried.
> Replaces blind retry with systematic diagnostic retry.

---

## 4-Phase Diagnostic Process

You MUST follow these phases in order. Do NOT skip to a fix without completing Phases 1-2.

### Phase 1: OBSERVE

Read the error output carefully. Answer these questions before proceeding:

- What is the **exact error message**? (Copy it verbatim, do not paraphrase.)
- What is the **exit code**?
- At which **line/step** did the failure occur?
- What was the **input** to the failing step?
- Is this the **same error** as the previous attempt, or a **different** one?

Do not interpret yet. Just collect facts.

### Phase 2: HYPOTHESIZE

List exactly 3 possible root causes, ordered from most likely to least likely:

```
Hypothesis 1 (most likely): [description]
Hypothesis 2: [description]
Hypothesis 3 (least likely): [description]
```

For each hypothesis, state what **observable evidence** led you to rank it at that position.

### Phase 3: TEST

For each hypothesis, describe:

| Hypothesis | Evidence that would CONFIRM it | Evidence that would DENY it | Quick check command/action |
|------------|-------------------------------|----------------------------|---------------------------|
| H1         |                               |                            |                           |
| H2         |                               |                            |                           |
| H3         |                               |                            |                           |

Execute the quick checks. Based on results, identify the confirmed root cause.

If no hypothesis is confirmed, form new hypotheses. Do NOT proceed to Phase 4 without a confirmed root cause.

### Phase 4: FIX

Apply the most **targeted** fix for the confirmed root cause.

- The fix MUST address the root cause, not mask the symptom.
- The fix MUST be the **minimum change** required.
- State explicitly: "Root cause: [X]. Fix: [Y]. Why this is not a workaround: [Z]."

---

## Anti-Blind-Retry Table

Before taking any retry action, check this table. If your planned action appears in the left column, STOP and use the correct action instead.

| Dangerous Action | Why It's Wrong | Correct Action |
|-----------------|----------------|----------------|
| Retry the same command unchanged | If it failed once with the same input, it will fail again. Identical input + identical environment = identical output. | Complete Phase 1-3 first. Change something based on diagnosis. |
| Add try/catch or error suppression around the failure | You are hiding the problem, not fixing it. The error will surface later in a harder-to-debug form. | Find why the error is thrown. Fix the cause, not the symptom. |
| Skip the failing step entirely | The step exists for a reason. Skipping it means downstream stages receive incomplete or invalid input. | Determine what the step produces and why it fails. Fix or replace with equivalent. |
| Increase timeout hoping it works | Timeouts usually indicate a hang, infinite loop, or wrong endpoint — not slowness. | Check what the process is actually doing during the wait. Profile or add logging. |
| Delete and recreate from scratch | Destroys diagnostic evidence. The same problem will likely recur. | Preserve the failing state. Diagnose in-place first. |
| Change multiple things at once | You won't know which change fixed it (or introduced new issues). | Change ONE thing. Test. Repeat if needed. |

---

## Previous Failure Context

This section is populated automatically when the retry is triggered.

```
PREVIOUS_ERROR_OUTPUT (last 500 chars):
{{previous_error_output}}

PREVIOUS_EXIT_CODE: {{previous_exit_code}}

ATTEMPT_NUMBER: {{attempt_number}} of {{max_attempts}}

DIAGNOSTIC_FOCUS: {{diagnostic_phase}}
```

Interpretation guide:
- **Attempt 1 failure**: Start from Phase 1 (OBSERVE). You have full diagnostic budget.
- **Attempt 2 failure**: You MUST be in Phase 3 (TEST) or Phase 4 (FIX). If you are still in Phase 1, you are moving too slowly.
- **Attempt 3+ failure**: You should be reporting BLOCKED if your fix did not work. Do not keep trying the same approach.

---

## Hard Gate: No Identical Retries

**If the same error message appears 2 or more times in a row, you are PROHIBITED from:**

1. Running the same command with the same arguments
2. Applying the same fix you already tried
3. Claiming "it might work this time"

You MUST change your approach. Acceptable changes include:
- A different fix based on a different hypothesis
- Requesting additional context or permissions
- Escalating to BLOCKED status with a clear explanation

**Enforcement**: Compare the current error output against `PREVIOUS_ERROR_OUTPUT`. If they match at 80%+ similarity, the hard gate is triggered. You must either try a fundamentally different approach or declare BLOCKED.

---

## Status Protocol for Retries

Every retry attempt MUST conclude with exactly one of these status codes:

### RETRY_FIXED
```
STATUS: RETRY_FIXED
ROOT_CAUSE: [One sentence describing the actual root cause]
FIX_APPLIED: [One sentence describing what you changed]
CONFIDENCE: [HIGH/MEDIUM/LOW that this resolves the issue permanently]
```
Use when: You identified the root cause via the 4-phase process and applied a targeted fix.

### RETRY_WORKAROUND
```
STATUS: RETRY_WORKAROUND
ROOT_CAUSE: [One sentence describing the actual root cause]
WORKAROUND: [One sentence describing what you did instead]
WHY_NOT_REAL_FIX: [Why the proper fix is not possible right now]
TECH_DEBT: [What needs to be done later to properly fix this]
```
Use when: You understand the root cause but cannot fix it properly (e.g., requires upstream change, missing permissions, external dependency).

### BLOCKED
```
STATUS: BLOCKED
ERROR_SUMMARY: [The error, in one sentence]
ATTEMPTS_MADE: [Number]
HYPOTHESES_TESTED: [List each hypothesis and its test result]
WHAT_WOULD_UNBLOCK: [Specific action needed from a human]
```
Use when: You have exhausted your diagnostic capacity. Be specific about what you need — "need help" is not acceptable. State exactly what information, permission, or action would unblock you.
