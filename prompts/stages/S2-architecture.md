# S2: Architecture Design

Design architecture for the feature described in the PRD.

## PRD
{{S1_output}}

## Project Context
- Java Maven multi-module
- Dubbo RPC + RocketMQ + Redis
- Existing modules: {{module_list}}

## Output
Write to: {{output_path}}/architecture.json

## Executable quality rules (opt-in)

When the project declares mechanical dependency or wire constraints, include them in
`contracts.quality_rules` with a stable ID, authoritative source, scoped input paths and
failure message. `imports` rules use the selected language parser, forbidden import
patterns and explicit test/demo exclusions. `wire` rules reference an API contract and
execute the project's serializer/HTTP probe; internal aliases are allowed if the observed
request/response fields and types match. Keep legal, violating and boundary examples in
the project's regression tests. Missing tools, parse errors and zero source files block.
