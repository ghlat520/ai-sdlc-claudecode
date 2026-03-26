# S5: Code Review

Review all code changes for this feature.

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

### Defect Classification
When reporting issues, classify each as:
- **A-Contract**: Frontend-backend field/param/structure mismatch
- **B-Stub**: Empty handler, missing endpoint, TODO placeholder
- **C-Data**: Missing seed data, empty pages
- **D-Integration**: Runtime error (AOP, SQL constraint, bean wiring)

## Output
Write to: {{output_path}}/review.json
