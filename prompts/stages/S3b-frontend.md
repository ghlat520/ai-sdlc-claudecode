# S3b: Frontend Development

Implement the frontend UI for this feature.

## Project Directory (WRITE CODE HERE)
{{project_dir}}

**CRITICAL**: All generated code files MUST be written to `{{project_dir}}/`, NOT to the pipeline docs directory. The pipeline docs directory (`{{output_path}}`) is only for stage metadata (output.json).

## Architecture
{{S2_output}}

## PRD
{{S1_output}}

## Backend APIs (SOURCE OF TRUTH — DO NOT DEVIATE)
{{S3_output}}

**CRITICAL**: The backend code above is the ONLY source of truth for:
- API endpoint URLs (copy exactly from `@GetMapping`/`@PostMapping` annotations)
- Request parameter names (copy exactly from `@RequestParam` names)
- Response field names (copy exactly from Entity/VO field names)
- Pagination structure (use exactly what backend returns)

DO NOT invent API paths, field names, or response structures. If the backend doesn't have an endpoint, DO NOT create a frontend button that calls it.

## Quality Lessons (from past deployments)
{{quality_lessons}}

## Rules
- Use Vant components where possible
- Responsive design
- Proper error handling and loading states
- Max 800 lines per file
- Avoid AI slop patterns (see anti-slop methodology): no purple gradients, no 3-column icon grids, no centered-everything layouts, no decorative blobs, no emoji as design elements

## Completeness Rules (CRITICAL — these prevent delivery failures)

### 1. ZERO empty handlers
- Every button `@click` MUST have a real implementation, not `// TODO` or empty function body
- Detail/View buttons MUST open a drawer/dialog showing all entity fields
- Export buttons MUST trigger a real download (match backend export endpoint URL exactly)
- If backend has no endpoint for an action, DO NOT render the button

### 2. Frontend-Backend Contract Alignment
- API file (`src/api/*.js`) MUST mirror backend Controller endpoints exactly
- Field names in `el-table-column prop` MUST match backend Entity field names
- `el-tree` label prop MUST match the actual field name returned by backend
- Search/filter params MUST match backend `@RequestParam` names exactly

### 3. Dashboard must use real data
- NEVER use `Promise.resolve({ data: null })` or hardcoded demo data
- Every chart/stat card MUST call a real backend API
- Use `Promise.all()` for parallel data loading on dashboard pages

### 4. Every list page must have
- Pagination with `el-pagination` bound to query params
- Search form with keyword + status filter at minimum
- Status tags with color-coded `el-tag`
- Detail drawer/dialog accessible from row click or action button
- Export button linked to backend CSV export endpoint

### 5. Import statements
- ALL used components/icons MUST be imported — never reference undefined variables
- Verify every `el-icon` component is imported from `@element-plus/icons-vue`

## Output
Write to: {{output_path}}/implementation.json
