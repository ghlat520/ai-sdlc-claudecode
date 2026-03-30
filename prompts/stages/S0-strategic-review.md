# S0: Deep Strategic Review

> Inspired by gstack `/plan-ceo-review` (18 cognitive patterns) + `/office-hours` (6 forcing questions).
> This is NOT a rubber stamp. Your job is to KILL bad ideas early and sharpen good ones.

## Feature Request
{{feature_description}}

## Product Discovery Input (if available)
{{S0p_output}}

---

## Phase 1: Forcing Questions (Answer ALL Before Proceeding)

Before any analysis, answer these 6 questions honestly. If you can't answer #1-#3 with confidence, recommend HOLD.

### Q1: Demand Reality
**"Who specifically has this problem, and how do we know they'll pay/use this?"**
- Not "users would love this" — WHO, specifically?
- What evidence exists? (user research, support tickets, churn data, competitor adoption)
- If the answer is "we think..." or "it seems like..." → flag as UNVALIDATED DEMAND

### Q2: Status Quo Alternative
**"What do users do TODAY without this feature?"**
- If the workaround is tolerable → the feature is nice-to-have, not must-have
- If users are leaving because of this → it's critical
- If users haven't complained → question whether demand exists at all

### Q3: Desperate Specificity
**"Can we describe the smallest version that solves the core problem?"**
- If scope is "build a comprehensive X" → it's too vague to evaluate
- If scope is "add Y to Z so that W can do V" → it's evaluable
- Force the description down to ONE sentence with ONE measurable outcome

### Q4: Narrowest Wedge
**"What is the absolute minimum we could ship to learn if this works?"**
- Not MVP (which often means "everything minus polish")
- The narrowest wedge: 1 user type, 1 workflow, 1 metric to validate
- If the wedge can't be defined → the problem isn't understood yet

### Q5: Observation Over Opinion
**"What would we measure to know this succeeded?"**
- Not "user satisfaction" — specific metrics with specific thresholds
- If we can't define success criteria → we can't evaluate the feature
- Define: metric + baseline + target + timeframe

### Q6: Future-Fit
**"If this feature succeeds, what does it make possible next? If it fails, what's the cost?"**
- Evaluate second-order effects, not just first-order
- Does this open or close future options?
- What's the reversal cost if this is wrong?

---

## Phase 2: Multi-Perspective Review

### Perspective 1: Business/CEO Review

Apply these cognitive patterns (select 3-5 most relevant):

| Pattern | Question | Source |
|---------|----------|--------|
| Regret Minimization | "In 5 years, will we regret NOT doing this?" | Bezos |
| Inversion | "What would make this a guaranteed failure?" | Munger |
| One-Way vs Two-Way Door | "Is this reversible? If yes, decide fast. If no, decide carefully." | Bezos |
| Opportunity Cost | "What are we NOT building by building this?" | Horowitz |
| 10x vs 10% | "Is this a 10x improvement or a 10% improvement?" | Page |
| Demand Pull vs Technology Push | "Are users pulling for this, or are we pushing it?" | Christensen |
| Time to Value | "How long until the FIRST user gets value from this?" | — |
| Competitive Moat | "Does this strengthen or weaken our competitive position?" | Buffett |

**Scope Mode** (choose one):
- **EXPANSION**: Feature opens new markets, revenue streams, or capabilities
- **SELECTIVE**: Feature improves existing workflows for existing users
- **HOLD**: Feature is not clearly justified — needs more evidence
- **REDUCTION**: Feature should be descoped or cancelled

**Required Output:**
- Scope decision with specific rationale (not "it aligns with strategy")
- Long-term trajectory: what this enables or prevents
- Business risks: competitive, market, resource, opportunity cost
- Strategy alignment: specific evidence, not vague "fits our vision"

### Perspective 2: Engineering Review

Evaluate technical feasibility and impact:
- Architecture impact: which modules/services affected? ({{module_list}})
- Breaking changes? Data migration? API versioning needed?
- Performance implications under current load (quantify: latency, throughput, storage)
- Technical debt: does this introduce or resolve debt?
- Effort sizing: S/M/L/XL with breakdown by component
- Dependency risk: are we blocked by external services or teams?

### Perspective 3: Design Review

Evaluate user experience impact:
- UX improvement/regression/neutral — be specific about which flows
- Design system consistency: uses existing patterns or needs new ones?
- Accessibility: WCAG 2.1 AA compliance requirements
- Mobile/responsive: are there platform-specific concerns?

---

## Phase 3: Anti-Sycophancy Guards

### HARD RULES — Never Say These:
- "That's a great idea!" → Instead: evaluate the idea on its merits
- "This is exciting!" → Instead: state what's good AND what's concerning
- "Users will love this" → Instead: cite evidence or say "unvalidated assumption"
- "This should be straightforward" → Instead: identify the hardest parts
- "I don't see any issues" → Instead: actively search for issues

### Pushback Patterns — Use When Needed:
- **Scope Creep Alert**: "The original ask was X, but this has grown to X+Y+Z. Can we ship X alone first?"
- **Assumption Challenge**: "This assumes [X]. What if [X] is wrong? What's our fallback?"
- **Evidence Request**: "What data supports this decision? I see opinion but not evidence."
- **Complexity Warning**: "This touches [N] modules. Each integration point is a failure risk."
- **Sunk Cost Check**: "Are we continuing because this is the best path, or because we've already started?"

---

## Phase 4: Scope Ceremony

For EVERY scope addition beyond the narrowest wedge:
1. **Identify**: What is being added?
2. **Justify**: Why can't this wait for v2?
3. **Cost**: What does adding this cost in time/complexity/risk?
4. **Decide**: Explicitly approve or defer each addition

This is the **Opt-in Ceremony**: nothing is in scope by default. Every addition must earn its place.

---

## Output Format

Produce a decision document with:
1. **Forcing Questions Answers** — honest answers to all 6 questions
2. **Scope decision** — EXPANSION/SELECTIVE/HOLD/REDUCTION with specific rationale
3. **Cognitive patterns applied** — which patterns, what they revealed
4. **Architecture risk matrix** — risk x impact for each technical concern
5. **Design score** — 0-10 per dimension (UX impact, consistency, accessibility)
6. **Go/No-Go recommendation** with hard conditions (what MUST be true to proceed)
7. **Anti-sycophancy flags** — any concerns that might be uncomfortable but must be stated
8. **Scope ceremony log** — any additions approved or deferred

**Status Protocol:**
- **GO** — All forcing questions answered, risks manageable, demand validated
- **CONDITIONAL-GO** — Proceed with specific conditions that must be met
- **NO-GO** — Insufficient evidence, too high risk, or demand unvalidated
- **NEEDS_CONTEXT** — Cannot evaluate without specific additional information

**Never recommend GO when the honest assessment is CONDITIONAL-GO or NO-GO.**

Write to: {{output_path}}/strategic-review.json
