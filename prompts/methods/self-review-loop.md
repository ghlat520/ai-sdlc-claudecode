## Multi-Perspective Self-Review Protocol

> You MUST complete all three phases before producing your final output.
> The final JSON output must reflect revisions from Phase 2 and Phase 3.

### Phase 1: Primary Generation

Generate your initial output as instructed by the stage prompt above.
**Do NOT output JSON yet.** Hold your initial draft internally.

### Phase 2: Adversarial Self-Critique

Now switch perspective. You are a **hostile critic** whose job is to find every weakness in the Phase 1 draft.

Apply these critique lenses (select all that apply):

| Lens | Question | Kill Signal |
|------|----------|-------------|
| **Demand Reality** | Is there evidence of real demand, or is this assumed? | "Users would love..." without data |
| **Specificity** | Are requirements specific enough to implement and test? | Vague words: "improve", "enhance", "better" |
| **Completeness** | What's missing that downstream stages will need? | Architecture can't be designed from this |
| **Consistency** | Do parts contradict each other? | FR says X, NFR implies not-X |
| **Testability** | Can every requirement be verified? | "Good performance" with no metric |
| **Scope Leak** | Has scope grown beyond what was approved? | Nice-to-haves disguised as must-haves |
| **Assumption Exposure** | What unstated assumptions does this rely on? | "Users will..." without validation |

**Output your critique as an internal working list.** Do NOT include it in the final JSON.
Flag at least 3 issues. If you can't find 3 real issues, you're not looking hard enough.

### Phase 3: Revision

Now revise your Phase 1 draft to address every issue found in Phase 2:
- For each critique point: fix it, strengthen it, or explicitly acknowledge it as a known limitation
- Verify no new issues were introduced by the fixes
- Ensure the final output is strictly better than the Phase 1 draft

### Final Output

Only NOW produce your JSON output — this must be the **Phase 3 revised version**, not the Phase 1 draft.

Your final JSON must include a `"self_review"` field (add to the top-level object):
```json
{
  "self_review": {
    "issues_found": 3,
    "issues_fixed": 2,
    "issues_acknowledged": 1,
    "confidence": "high|medium|low",
    "remaining_concerns": ["any issues that couldn't be fully resolved"]
  }
}
```

**HARD GATE**: If you skip Phase 2 and Phase 3 and just output Phase 1 directly, your output is low quality by definition. The critique phase IS the quality mechanism.
