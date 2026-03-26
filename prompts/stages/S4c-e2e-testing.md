# S4c: E2E Testing

Write E2E tests for critical user journeys.

## PRD User Stories
{{S1_output}}

## Frontend
{{S3b_output}}

## Backend APIs
{{S3_output}}

## Requirements
- Cover all critical user flows from PRD
- Use Playwright for browser automation
- Tests MUST be executable via `npx playwright test`
- Include proper setup/teardown (baseURL, auth fixtures)
- Screenshot on failure saved to test-results/
- Test responsive layouts

## Output
Write to: {{output_path}}/e2e-testing.json
