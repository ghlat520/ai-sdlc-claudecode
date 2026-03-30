# S4e: Browser QA (Exploratory)

Explore the running application like a real user. Do NOT write test scripts — use gstack browse CLI to navigate, click, fill forms, and verify behavior against the PRD user stories.

## PRD User Stories
{{S1_output}}

## Frontend Implementation
{{S3b_output}}

## Backend APIs
{{S3_output}}

## Setup

```bash
# Locate gstack browse binary
B=""
[ -x ~/.claude/skills/gstack/browse/dist/browse ] && B=~/.claude/skills/gstack/browse/dist/browse
if [ ! -x "$B" ]; then
  echo "SKIP: gstack browse binary not found"
  exit 0
fi
echo "BROWSE_READY: $B"
```

If browse binary not found, output status "skipped" with reason and exit — do not fail the pipeline.

## Target URL

Use the URL provided in `{{app_url}}`. If not set, default to `http://localhost:8080`.

## Exploration Protocol

For EACH user journey from the PRD:

### 1. Navigate and snapshot
```bash
$B goto {{app_url}}
$B snapshot -i
```

### 2. Follow the user journey step by step
For each step in the user story:
- `$B click @ref` / `$B fill @ref "value"` / `$B select @ref "option"`
- `$B snapshot -D` after each action (diff shows what changed)
- `$B console --errors` after each page transition (catch JS errors)
- `$B network` after form submissions (verify API calls succeed)

### 3. Screenshot evidence
```bash
$B screenshot {{output_path}}/screenshots/journey-name-step-N.png
```

### 4. Check 7 categories per page
| Category | How to check |
|----------|-------------|
| Visual/UI | `$B snapshot -i` — look for layout breaks, missing elements |
| Functional | Click every button/link — does it do what it says? |
| Forms | Submit empty, invalid, edge-case data |
| Console errors | `$B console --errors` — any JS exceptions? |
| Network errors | `$B network` — any 4xx/5xx responses? |
| Performance | `$B perf` — page load > 3s? |
| Content | Read all text — typos, placeholder text, truncation? |

### 5. Edge cases to always try
- Empty form submission
- Very long text input (500+ chars)
- Special characters in inputs (`<script>`, `'`, `"`, `&`)
- Back button after form submission
- Double-click on submit buttons
- Refresh mid-flow

## Issue Severity

| Severity | Definition |
|----------|-----------|
| critical | Blocks core workflow, data loss, crash |
| high | Major feature broken, no workaround |
| medium | Feature works but noticeably wrong, workaround exists |
| low | Cosmetic, typo, minor alignment |

## Output

Produce a JSON report with:
- Each journey explored (name, steps taken, pass/fail)
- Each issue found (severity, category, description, screenshot path, reproduction steps)
- Health score (0-100): 100 = zero issues, -25 per critical, -10 per high, -5 per medium, -1 per low
- Summary: total pages visited, total issues by severity

Write to: {{output_path}}/browser-qa.json
