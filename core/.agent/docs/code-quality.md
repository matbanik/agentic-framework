# Code Quality Standards

> Referenced from `AGENTS.md`. Contains detailed examples and forbidden patterns.

## Tiered Quality Model

### Maximum Tier (core, infrastructure, api, mcp-server)

- Read the ENTIRE file before modifying it
- NEVER use "// rest of implementation here" or "// ... existing code ..."
- Handle ALL error states explicitly — no silent failures
- Every function must have input validation
- Write the COMPLETE implementation, not a skeleton
- No `TODO` comments — implement it or create an issue
- No `any` type in TypeScript — use proper types
- No empty `catch {}` — handle or re-throw with context
- No `console.log` — use structured logging (`structlog`)
- Docstrings on every exported function/class

#### Boundary Validation Standards (Maximum Tier)

- **Validate at the first trust boundary** — API route, MCP tool handler, or UI form submit
- **Reject unknown fields** — use `extra="forbid"` (Pydantic) or `.strict()` (Zod), or explicitly document why extra fields are allowed
- **Do NOT rely on dataclass/type-hint annotations as runtime validation** — Python type hints are not enforced at runtime; `assert` is stripped under `-O`
- **Do NOT use `replace(obj, **raw_input)` or `Model(**{**old, **updates})` on external input** without prior boundary schema validation
- **Keep create/update invariant logic centralized** — partial updates must pass through the same validation as creates

##### Forbidden Boundary Patterns

```python
# ❌ NEVER — raw dict from request body used directly
def update(self, id: str, updates: dict[str, Any]) -> Entity:
    existing = repo.get(id)
    return replace(existing, **updates)  # bypasses all validation

# ✅ ALWAYS — validated model at boundary, invariants in service
class UpdateRequest(BaseModel, extra="forbid"):
    name: str = Field(min_length=1)
    # ...

def update(self, id: str, cmd: UpdateCommand) -> Entity:
    existing = repo.get(id)
    # apply validated fields with invariant checks
```

### Balanced Tier (ui/)

- No placeholders or skeleton code
- Basic error handling required (no empty catch)
- `TODO` allowed ONLY if referencing a tracked issue (e.g., `// TODO(#42): add animation`)
- `console.warn` allowed for development debugging
- Docstrings only on complex/non-obvious components

## Forbidden Patterns

### Python

```python
# ❌ NEVER
except Exception:
    pass

# ✅ ALWAYS
except SpecificError as e:
    logger.error("operation_failed", error=str(e), context=ctx)
    raise
```

### TypeScript

```typescript
// ❌ NEVER
catch (e) {}

// ✅ ALWAYS
catch (e: unknown) {
  logger.error('Operation failed', { error: e instanceof Error ? e.message : String(e) });
  throw;
}
```
