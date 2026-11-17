# S10: Release & Rollout

Prepare a release decision brief for this feature. This stage prepares material; it does
not deploy or authorize a release. Cite the supervisor's current project acceptance status,
declared scope and candidate. If no contract is configured, report not_evaluated. List
missing, stale or failed evidence and the next owner/action; never infer product acceptance
from stage counts, self-reported completion or review scores. A local fix cannot close the
whole delivery while a required case or known blocking finding remains unresolved.

## Deployment Plan
{{S6_output}}

## Monitoring
{{S7_output}}

## Documentation
{{S8_output}}

## Performance
{{S9_output}}

## Generate
- Release version
- Complete checklist
- Detailed rollback plan
- Deployment strategy (canary/blue-green/rolling)
- Stakeholder notifications

## Output
Return the release JSON, keeping execution completion, project acceptance and human release
decisions separate. Notifications are drafts. The supervisor stores the artifact.
