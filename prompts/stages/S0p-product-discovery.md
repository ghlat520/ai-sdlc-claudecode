# S0p: Product Discovery

> Pre-pipeline stage for transforming vague ideas into evaluable feature descriptions.
> Inspired by BMAD's product-brief + PRFAQ methodology + domain-research.
> This stage is OPTIONAL — skip when the feature description is already specific and well-defined.

## Raw Input
{{raw_idea}}

## Skip Conditions (Auto-Pass)

If the input already contains ALL of these, skip discovery and pass through to S0:
- [ ] Specific user role/persona identified
- [ ] Clear problem statement (not solution statement)
- [ ] Measurable success criteria
- [ ] Defined scope boundary

If 3+ are missing → run full discovery below.

---

## Phase 1: Problem Validation

### Step 1: Problem Statement Extraction

Transform the raw idea into a problem statement:

**Template**: "{User role} currently cannot {capability} because {blocker}, which causes {business impact}."

**Anti-patterns to reject**:
- Solution masquerading as problem: "We need a dashboard" → WHY do you need a dashboard?
- Feature request without context: "Add export" → WHO needs to export WHAT and WHY?
- Technology-first thinking: "We should use Kafka" → WHAT problem does Kafka solve here?

### Step 2: Demand Signal Assessment

Evaluate evidence of real demand:

| Signal Type | Evidence Level | Examples |
|-------------|---------------|----------|
| **Strong** | Direct user request + data | Support tickets, churn analysis, user interviews |
| **Medium** | Indirect signals | Competitor feature, market trend, internal stakeholder ask |
| **Weak** | Opinion only | "I think users want...", "It would be cool if..." |
| **None** | Pure speculation | No evidence cited |

**Output**: Evidence level + specific supporting data points.

### Step 3: Market & Domain Context

Research the problem space:
- How do competitors solve this? (at least 2 examples)
- Are there open-source or SaaS solutions that address this?
- What's the industry-standard approach?
- Any regulatory or compliance considerations?

---

## Phase 2: Solution Shaping

### Step 4: PRFAQ Method (Amazon Working Backwards)

Write a mini press release (3-5 sentences):
1. **Headline**: One sentence announcing the feature as if it shipped
2. **Problem**: What problem did customers have?
3. **Solution**: How does this feature solve it?
4. **Customer Quote**: A realistic user reaction (not "I love it!" — something specific)
5. **Getting Started**: How does a user start using this?

### Step 5: User Persona Definition

For each affected user role:
```
Persona: {Name/Role}
Goal: {What they want to achieve}
Current Pain: {What blocks them today}
Success Looks Like: {Observable behavior change}
Technical Context: {Devices, access patterns, frequency}
```

### Step 6: Narrowest Viable Feature (NVF)

Define the absolute minimum that validates the hypothesis:
- **One** user persona
- **One** workflow
- **One** success metric
- **Zero** nice-to-haves

The NVF is NOT the MVP. It's the experiment that tells you if the MVP is worth building.

---

## Phase 3: Output Assembly

### Step 7: Feature Description Synthesis

Produce a structured feature description that S0 (Strategic Review) can evaluate:

```json
{
  "title": "Feature title (< 10 words)",
  "problem_statement": "The validated problem statement from Step 1",
  "demand_evidence": {
    "level": "strong|medium|weak|none",
    "data_points": ["specific evidence items"]
  },
  "personas": [{"role": "...", "goal": "...", "pain": "..."}],
  "press_release": "The 3-5 sentence PRFAQ from Step 4",
  "narrowest_viable_feature": {
    "persona": "Single persona",
    "workflow": "Single workflow",
    "success_metric": "Single measurable metric",
    "validation_method": "How we'll know if it works"
  },
  "scope_boundary": {
    "in_scope": ["specific items"],
    "explicitly_out": ["specific items with rationale"]
  },
  "domain_context": {
    "competitor_approaches": ["how competitors solve this"],
    "compliance_flags": ["any regulatory concerns"],
    "technical_constraints": ["known constraints"]
  }
}
```

---

## Integration Notes

This stage feeds into:
- **S0 (Strategic Review)**: Uses the structured feature description for multi-perspective review
- **S1 (Requirements)**: Uses personas, demand evidence, and domain context for PRD generation

When running as part of the automated pipeline:
- This stage uses `human-required` gate because product discovery benefits from human input
- For well-defined features, auto-skip and pass raw_idea directly as feature_description to S0
- The skip detection is deterministic: check for 4 criteria, if 3+ present → skip

Write to: {{output_path}}/product-discovery.json
