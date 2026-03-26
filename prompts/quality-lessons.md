# Quality Lessons — Accumulated from Deployment Retrospectives

> These lessons are injected into S3, S3b, and S5 prompts via `{{quality_lessons}}`.
> Update this file after every deployment retrospective.

---

## Lesson 1: Frontend MUST NOT independently invent API contracts
**Source**: SRM Platform (2026-03-26), 5 bugs (33% of total)
**Problem**: Frontend and backend generated independently from the same design doc produced different field names, param names, and response structures.
**Rule**: Frontend code generation MUST receive backend Controller source code as input and treat it as the ONLY source of truth for API URLs, field names, and response structures.
**Examples**:
- Backend returned `menuName`, frontend used `name` in el-tree → blank tree nodes
- Frontend sent `businessCategory` param, backend didn't accept it → filter broken
- Backend returned `{ records, total }`, frontend expected `{ list, count }` → empty table

## Lesson 2: Empty function bodies pass compilation but break delivery
**Source**: SRM Platform (2026-03-26), 4 bugs (27% of total)
**Problem**: `const openDetail = (row) => { // open detail drawer }` compiles and passes lint but does nothing at runtime.
**Rule**: Every UI button/action MUST have a non-empty implementation. If the backend endpoint doesn't exist yet, DO NOT render the button. Scan for `=> { }` and `=> { //` patterns.
**Examples**:
- 4 detail/view buttons with empty handlers → clicking did nothing
- 3 export buttons calling non-existent backend endpoints → 500 errors
- Dashboard showing hardcoded `Promise.resolve({ data: null })` → all zeros

## Lesson 3: Seed data must cover every page and every status
**Source**: SRM Platform (2026-03-26), 3 bugs (20% of total)
**Problem**: Pages loaded correctly but displayed empty because H2 had no matching data.
**Rule**: SQL init scripts MUST insert ≥5 rows per table, with at least 1 row per status value. Status-filtered pages (audit review, blacklist, pending approval) are especially prone to this.
**Examples**:
- Audit log page blank — no log entries in seed data
- Supplier review page blank — no `under_review` status suppliers
- Blacklist page blank — no `blacklisted` status suppliers

## Lesson 4: Compilation ≠ Runnable
**Source**: SRM Platform (2026-03-26), 3 bugs (20% of total)
**Problem**: `mvn compile` passed but the application threw runtime errors (NPE in AOP, NOT NULL constraint violations, MyBatis mapper errors).
**Rule**: Pipeline MUST actually start the application and send at least one HTTP request per endpoint to verify runtime correctness. Static analysis alone is insufficient.
**Examples**:
- AuditLogAspect tried to insert NULL entity_id → SQL constraint violation
- Auto-generated supplier_code was NULL → NOT NULL column failed
- Maven multi-module ran with stale classes → ClassNotFoundException

## Lesson 5: CSV export is a universal requirement
**Source**: SRM Platform (2026-03-26)
**Problem**: Every list page needs an export button, but none were generated.
**Rule**: For every list page, generate both backend CSV export endpoint (HttpServletResponse + PrintWriter + UTF-8 BOM) and frontend download button. No external library needed.

## Lesson 6: Dashboard data must be real
**Source**: SRM Platform (2026-03-26)
**Problem**: Dashboard was generated with hardcoded demo numbers and placeholder charts.
**Rule**: Dashboard MUST query real data using COUNT/SUM/GROUP BY. Required endpoints: /stats (KPI summary), /trend (monthly data), /top-N (rankings), /todos (pending actions).
