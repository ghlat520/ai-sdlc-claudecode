# S3b: Frontend Development

Implement the approved interface in `{{project_dir}}` using the declared frontend
module and design system. Stage metadata belongs in `{{output_path}}`.

## Architecture and API contracts
{{S2_output}}

## Approved requirements and executable behavior map
{{S1_output}}

## Applicable quality lessons
{{quality_lessons}}

- Read the existing frontend, wire contract and module build/test commands first.
- Implement the declared user actions, loading, failure, retry and visible results.
- Bind requests and rendered values to actual serialized API fields. Use explicit
  conversions when internal names differ. Verify them through API and UI assertions.
- Enforce the declared process/layer dependency rules; renderer code uses supported APIs.
- Production uses real API providers. Approved test/demo providers stay in their scopes.
- Lists, filters, export actions, charts and UI libraries follow approved requirements.
  Element Plus, Vue, React or a particular component library is not a universal default.
- Use the selected target's compiler/linter and tests. Required Web/H5/native/desktop
  journeys need their own real target identity and execution evidence.
- Preserve useful comments. A permitted empty callback needs the project's narrow exception.

Write implementation files in the declared module and emit schema-compliant metadata.
