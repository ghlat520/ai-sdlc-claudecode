# S5: Code Review

Review all code changes for this feature.

Start from the approved project contract and current candidate. Search every equivalent
rule and call site implicated by a fix, including normal behavior and necessary rejection
cases. The checks below apply where required by that contract; do not invent endpoints or
features solely to satisfy a generic checklist. Keep open and fix_submitted findings visible
until their named checks verify closure. Report source, package, runtime and business evidence
separately. An author self-check is not an independent review, and a review score cannot
override a failed required check or establish project acceptance.

## Changed Files
{{S3_output.files_changed}}
{{S3b_output.files_changed}}

## Quality Lessons (from past deployments)
{{quality_lessons}}

## Check For

### Standard Checks
- Code quality (naming, structure, complexity)
- Security vulnerabilities (OWASP Top 10)
- Performance issues
- Immutability violations

### Completeness Checks (CRITICAL — delivery quality)

#### Backend Completeness
- [ ] **Every entity has CRUD + detail + export endpoints** — scan all Controllers for missing methods
- [ ] **Seed data exists for every table** — check SQL files, verify ≥5 rows per table
- [ ] **Seed data covers all statuses** — for tables with status fields, verify each status has ≥1 row
- [ ] **Dashboard endpoints return real aggregated data** — no hardcoded values
- [ ] **AOP aspects handle nullable fields** — check audit log, auto-fill interceptors
- [ ] **Application can start** — verify no circular dependencies, missing beans, or SQL errors

#### Frontend Completeness
- [ ] **ZERO empty function bodies** — grep for `=> { }`, `=> { // `, `() { }` patterns
- [ ] **Every button has real handler** — no TODO, no empty click handlers
- [ ] **All imports present** — especially icons from @element-plus/icons-vue
- [ ] **API paths match backend exactly** — cross-reference frontend api/*.js with backend Controllers
- [ ] **Field names match backend exactly** — cross-reference el-table-column props with Entity fields
- [ ] **el-tree label props match actual field names** — not assumed names
- [ ] **Dashboard uses real API calls** — no Promise.resolve with null/hardcoded data
- [ ] **Export buttons have matching backend endpoints** — verify CSV download works

#### Frontend-Backend Contract
- [ ] **Parameter names aligned** — frontend query params == backend @RequestParam names
- [ ] **Response structure aligned** — frontend data extraction matches backend response wrapper
- [ ] **Pagination aligned** — frontend uses same page/size params and reads same total/records fields

### Browser QA Findings (if available)
{{S4e_output}}
If browser QA results are available, cross-reference each reported issue with the source code:
- For each critical/high issue, identify the root cause file and line
- Verify the issue is reproducible from the code
- Add to the defect list with classification

### Defect Classification
When reporting issues, classify each as:
- **A-Contract**: Frontend-backend field/param/structure mismatch
- **B-Stub**: Empty handler, missing endpoint, TODO placeholder
- **C-Data**: Missing seed data, empty pages
- **D-Integration**: Runtime error (AOP, SQL constraint, bean wiring)

## Output
Return the review JSON with findings, evidence, scope and remaining gaps. The supervisor
stores the artifact; its acceptance calculation owns the project verdict.
