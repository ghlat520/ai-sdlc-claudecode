## TDD Methodology (Mandatory)

**Iron Law: NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST**

### Red-Green-Refactor Cycle
1. **RED** — Write one minimal failing test showing desired behavior
2. **Verify RED** — Run test, confirm it fails for the RIGHT reason (feature missing, not typo)
3. **GREEN** — Write simplest code to pass the test. No extras.
4. **Verify GREEN** — Run test, confirm it passes. All other tests still pass.
5. **REFACTOR** — Clean up. Keep tests green. Don't add behavior.
6. **Commit** — One commit per red-green-refactor cycle.

### Anti-Rationalization
| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. Test takes 30 seconds. |
| "I'll test after" | Tests written after pass immediately — proves nothing. |
| "Need to explore first" | Fine. Throw away exploration, then start with TDD. |
| "TDD will slow me down" | TDD is faster than debugging. |

### Red Flags — STOP and Start Over
- Code written before test
- Test passes immediately (you're testing existing behavior)
- Can't explain why test failed
- "Just this once" rationalization

**Violating the letter of these rules IS violating the spirit.**
