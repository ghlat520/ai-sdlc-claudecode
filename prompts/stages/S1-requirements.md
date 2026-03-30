# S1: Deep Requirements Analysis

> Inspired by BMAD 12-step PRD workflow + CSV domain-adaptive routing.
> This is NOT template-filling. This is structured discovery that produces a machine-verifiable PRD.

## Feature Request
{{feature_description}}

## Strategic Review Output
{{S0_output}}

## Product Discovery Output (if available)
{{S0p_output}}

## Context Files
{{context_files}}

---

## Phase 1: Domain Classification & Adaptive Routing

### Step 1: Classify the Project Domain

Evaluate which domain(s) this feature belongs to. Each domain triggers specific requirements:

| Domain | Triggers | Compliance/Extra Requirements |
|--------|----------|-------------------------------|
| Healthcare | Patient data, clinical workflows | HIPAA, audit logging, PHI encryption, BAA |
| Finance | Transactions, payments, portfolios | PCI-DSS, SOX, audit trails, reconciliation |
| E-Commerce | Cart, checkout, inventory | PCI, tax calculation, shipping integration |
| Enterprise SaaS | Multi-tenant, permissions | RBAC, tenant isolation, SSO, data export |
| Real-time/Streaming | Live data, websocket | Latency SLAs, backpressure, reconnection |
| Data Pipeline | ETL, analytics, reporting | Idempotency, exactly-once, data lineage |
| API Platform | Developer-facing APIs | Rate limiting, versioning, SDK generation |
| Mobile | Native/hybrid app features | Offline mode, push notifications, deep links |
| IoT/Embedded | Device communication | Protocol handling, firmware updates, telemetry |
| AI/ML | Model serving, training | Model versioning, A/B testing, bias monitoring |
| Government | Public sector systems | Section 508, WCAG AAA, data sovereignty |
| Gaming | Game mechanics, matchmaking | Anti-cheat, leaderboard integrity, session management |
| Social | User-generated content, feeds | Content moderation, spam detection, privacy |
| Internal Tool | Back-office, admin | Audit log, bulk operations, CSV export |
| General | None of the above | Standard requirements only |

**Output**: Domain classification + triggered compliance requirements (if any).

### Step 2: Classify the Project Type

| Type | Characteristics | Required Sections |
|------|----------------|-------------------|
| New Product | Greenfield, no existing code | Full PRD: vision, personas, journey maps, all NFRs |
| New Feature | Extension of existing product | Focused PRD: affected modules, integration points, migration |
| Bug Fix (Complex) | Systemic fix requiring design | Root cause analysis, affected areas, regression plan |
| Refactoring | No behavior change, internal improvement | Current vs target architecture, migration plan, rollback |
| Integration | Connecting external systems | API contracts, error handling, retry strategy, circuit breaker |
| Performance | Optimization, scaling | Benchmarks, profiling data, target metrics |
| Migration | Moving between systems/versions | Data mapping, rollback plan, feature parity checklist |

**Output**: Project type + dynamically selected required sections.

---

## Phase 2: Structured Requirements Discovery

### Step 3: Executive Summary Generation

Write a 3-5 sentence executive summary that answers:
1. **What** are we building? (one sentence, specific)
2. **Who** benefits? (specific user role/persona)
3. **Why** now? (business driver — from S0 strategic review)
4. **How** will we know it worked? (primary success metric)

**Quality bar**: Every sentence must carry information weight. No filler ("In today's fast-paced..."), no buzzwords ("leveraging AI to..."), no vague claims ("improve user experience").

### Step 4: Success Criteria (SMART)

Define measurable success criteria across three horizons:

| Horizon | Timeframe | Example Metric |
|---------|-----------|---------------|
| **MVP** | Week 1-2 post-launch | Core workflow completion rate > X% |
| **Growth** | Month 1-3 | Adoption rate, retention, NPS delta |
| **Vision** | Month 6+ | Revenue impact, market position |

Each metric MUST be: Specific, Measurable, Achievable, Relevant, Time-bound.

### Step 5: User Journey Mapping

For each primary user role, write a narrative journey (not just steps):
- **Opening**: User's current state and motivation
- **Rising Action**: Steps toward their goal, including decision points
- **Climax**: The critical moment where value is delivered
- **Resolution**: Completion state and next actions

Minimum 3 user journeys. Each journey should expose integration points and edge cases.

### Step 6: Domain-Specific Requirements (Conditional)

Only generate this section if the domain classification (Step 1) triggered compliance requirements.

For each triggered requirement:
- Specific regulation/standard and section
- What it requires in this context
- Implementation constraint
- Verification method

### Step 7: Functional Requirements

Generate 20-50 functional requirements in this format:
```
FR-{N}: As a {role}, the system SHALL {capability} when {condition} so that {benefit}.
Priority: must | should | could | wont
Acceptance: {testable condition}
```

**Rules**:
- Implementation-agnostic (WHAT, not HOW)
- Each FR is independently testable
- No duplicate capabilities across FRs
- Prioritize using MoSCoW strictly: "must" = cannot ship without it

### Step 8: Non-Functional Requirements

Generate NFRs in this format:
```
NFR-{N}: The system SHALL {metric} {condition} as measured by {method}.
Category: performance | security | scalability | reliability | usability
Target: {specific threshold}
```

**Mandatory NFR categories** (at minimum):
- Response time (p50, p95, p99)
- Availability target (e.g., 99.9%)
- Data consistency guarantees
- Security requirements (authentication, authorization, encryption)
- Scalability limits (concurrent users, data volume)

### Step 9: Scope Boundary

Explicitly list:
- **In scope**: What we ARE building (from scope ceremony in S0)
- **Out of scope**: What we are NOT building (and why)
- **Deferred**: What we might build later (and trigger conditions)

---

## Phase 3: Quality Verification

### Step 10: Cross-Reference Check

Verify internal consistency:
- Every user story maps to at least one FR
- Every FR maps to at least one acceptance criterion
- Every NFR has a measurable target
- No orphan requirements (FR without user story justification)
- S0 scope ceremony decisions are reflected in scope boundary

### Step 11: Downstream Readiness Check

Verify the PRD is sufficient for architecture design (S2):
- [ ] All external system integrations identified
- [ ] Data model requirements clear (entities, relationships)
- [ ] API boundaries defined (what's internal vs external)
- [ ] Performance targets quantified (not "fast" — specific numbers)
- [ ] Security requirements specific enough to design against

### Step 12: Output Assembly

Assemble the final PRD JSON with all sections. Include:
- Domain classification and triggered compliance
- Project type and dynamically selected sections
- All requirements with IDs and priorities
- Acceptance criteria in Given/When/Then format
- Scope boundary with rationale

---

## Anti-Pattern Detection

Flag and reject these patterns in your own output:
- Vague requirements ("improve performance", "enhance UX")
- Implementation-specific language ("use Redis", "add a button")
- Missing acceptance criteria
- "Nice to have" items disguised as "must have"
- Requirements that can't be tested
- Circular dependencies between requirements

---

## Output

Write the complete PRD to: {{output_path}}/requirements.json

The output MUST conform to the requirements-output schema and include ALL required fields.
Every functional requirement must have a testable acceptance criterion.
Every non-functional requirement must have a measurable target.
