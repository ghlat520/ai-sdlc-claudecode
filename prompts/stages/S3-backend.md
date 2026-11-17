# S3: Backend Development

Implement the approved backend behavior in `{{project_dir}}` using the declared
module paths and toolchain. Stage metadata belongs in `{{output_path}}`.

## Architecture and contracts
{{S2_output}}

## Approved requirements and function map
{{S1_output}}

## Applicable quality lessons
{{quality_lessons}}

## Rules
- Read the owning call chain, existing implementations and declared module checks.
- Implement the approved operations, validation, authorization and observable state changes.
- Preserve API wire semantics, including explicit lawful field conversions. Internal names
  do not have to match external names; actual serialized requests/responses must match S2.
- Exercise failure, retry, concurrency and persistence where required by the function map.
- Run the module's actual build, static checks and tests; report command failures directly.
- Keep useful comments for business constraints, concurrency and protocols.
- Implement exports, dashboard queries, pagination or demo data only when the approved
  requirements call for them. Use language-specific conventions of the selected framework.
- Java/Spring annotations and response writers apply only to an explicitly selected Java/Spring
  module. They are not requirements for Python, Node, Go or other backends.
- Do not substitute mock data in production paths. Tests and approved demo profiles may use
  isolated fixtures with explicit scope. Production contracts remain independently tested.

## Output
Write implementation files to the declared module paths and metadata to
`{{output_path}}/implementation.json` using the configured schema.
