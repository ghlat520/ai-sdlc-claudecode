# S0: Strategic Review

Review the feature request from three perspectives before implementation begins.

## Feature Request
{{feature_description}}

## Perspective 1: Business/CEO Review
Evaluate the feature from a business strategy standpoint:
- Is the scope right? (Expand / Hold / Reduce)
- What's the long-term trajectory if we build this?
- What are the risks to the business (competitive, market, resource)?
- Does this align with current product strategy?
- What's the opportunity cost of building this vs. something else?

## Perspective 2: Engineering Review
Evaluate the technical feasibility and impact:
- Architecture impact assessment (which modules/services affected?)
- Breaking changes? Data migration needed?
- Performance implications under current load?
- Technical debt introduced or resolved?
- Estimated engineering effort (T-shirt sizing: S/M/L/XL)

## Perspective 3: Design Review
Evaluate the user experience impact:
- User experience impact (improvement/regression/neutral)
- Design system consistency (uses existing patterns or needs new ones?)
- Accessibility considerations (WCAG compliance requirements)
- Mobile/responsive considerations

## Output Format
Produce a decision document with:
1. **Scope decision** — expand/hold/reduce with rationale
2. **Architecture risk matrix** — risk × impact for each technical concern
3. **Design score** — 0-10 per dimension (UX impact, consistency, accessibility)
4. **Go/No-Go recommendation** with conditions (what must be true to proceed)

Write to: {{output_path}}/strategic-review.json
