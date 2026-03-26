# S3: Backend Development

Implement the backend code for this feature.

## Project Directory (WRITE CODE HERE)
{{project_dir}}

**CRITICAL**: All generated code files MUST be written to `{{project_dir}}/`, NOT to the pipeline docs directory. The pipeline docs directory (`{{output_path}}`) is only for stage metadata (output.json).

## Architecture
{{S2_output}}

## PRD
{{S1_output}}

## Quality Lessons (from past deployments)
{{quality_lessons}}

## Rules
- Follow existing code patterns
- Immutable objects only
- Handle all errors explicitly
- Max 800 lines per file

## Completeness Rules (CRITICAL — these prevent delivery failures)

### 1. Every CRUD must be FULLY implemented
- List with pagination + keyword search + status filter
- Create with validation
- Update with validation
- Delete (soft delete if applicable)
- **Detail/getById endpoint** — NEVER omit this
- **Export endpoint (CSV)** — Every list page MUST have an export API using HttpServletResponse + PrintWriter + UTF-8 BOM

### 2. Seed Data (MANDATORY for demo-ready delivery)
- Every table referenced by a list page MUST have ≥5 seed data rows in SQL init scripts
- Status-filtered pages MUST have data in EACH status (e.g., pending, approved, rejected)
- Relational data must be consistent (foreign keys must reference existing records)

### 3. Dashboard/Statistics endpoints
- If the PRD includes a dashboard, implement REAL aggregation queries (COUNT, SUM, GROUP BY)
- NEVER use hardcoded demo data — always query from the database
- Include: summary stats, trend data (last 6 months), top-N rankings, pending action counts

### 4. AOP/Interceptor safety
- Audit log aspects MUST handle nullable fields (entity_id can be null for some operations)
- Auto-fill interceptors MUST not throw on missing fields
- Test that the application can START and serve at least one GET request

### 5. API Contract clarity
- Every Controller method MUST have explicit `@RequestParam` or `@RequestBody` annotations
- Response wrapper MUST be consistent: `{ code, message, data }` for single objects, `{ code, message, data: { records, total } }` for paginated lists
- Field names in Entity MUST match what the frontend will consume — use `@JsonProperty` if needed

## Output
Write to: {{output_path}}/implementation.json
