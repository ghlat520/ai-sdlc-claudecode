# S4e: Terminal Journey QA

Execute the required journeys from the frozen function map against the running
candidate, using the project's available browser or native driver.

## Requirements and map
{{S1_output}}

## Implementations
{{S3_output}}
{{S3b_output}}

- Record exact target, browser/device/version, viewport or package identity. Browser
  viewport emulation is labeled as emulation; native packages and WebViews need their
  own drivers and evidence.
- Execute authenticated actions, failure feedback, retry and observable data results.
  Compare the page, requests and relevant persistent state in the same scenario.
- Save a trace, screenshot, request log and data readback under this run/attempt.
  Required steps, targets and artifacts must match the current candidate contract.
- Required tool absence, zero steps, skipped/error steps, stale reports and target
  mismatch remain unverified and block acceptance. Discover existing local tools
  before declaring an environment gap. Do not substitute a high health score.
- Measure declared performance budgets through actual execution, with units and target.
- Exploratory observations supplement required regression journeys; they cannot close
  an unexecuted required check. Report failed observations and unresolved blockers.

Emit stage metadata using the configured browser QA schema. The supervisor's
post-commands collect actual journey results; model prose cannot grant acceptance.
