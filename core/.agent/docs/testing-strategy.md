# Testing Strategy

PROFILE D6 is authoritative. Language tools, coverage numbers and layer layouts below
are software examples to select or replace during adoption, not universal defaults. — {{PROJECT_NAME_TITLE}}

## Test Pyramid

```
         ┌─────────┐
         │  E2E    │  Few — Playwright (UI), TestClient (API)
         ├─────────┤
         │ Integr. │  Medium — Real DB (in-memory SQLite)
         ├─────────┤
         │  Unit   │  Many — Pure logic, no I/O
         └─────────┘
```

## TUI Test Pyramid

The Go TUI (`tui/`, `charm.land/bubbletea/v2`) has its own four-tier pyramid. Use the cheapest tier that proves the property; reserve real-binary E2E for what only it can prove (the *shipped binary* renders and responds under a real terminal).

```
         ┌──────────────────────┐
         │  Real-binary E2E     │  Few — tuitest harness: compiled binary in a real PTY (MEU-344)
         ├──────────────────────┤
         │  app.Model + httptest│  Medium — in-process keystroke→render→backend (no PTY)
         ├──────────────────────┤
         │  Golden snapshots    │  Medium — screens/*_test.go render-only goldens (layout drift)
         ├──────────────────────┤
         │  Unit                │  Many — pure logic (ParseKeys, formatters, AssertZones)
         └──────────────────────┘
```

| Tier | Where | Command | Proves |
|------|-------|---------|--------|
| Unit | `tui/internal/**/_test.go` (default build) | `go -C tui test ./...` | Pure logic, helpers, `tuitest.ParseKeys`/`AssertZones`. |
| Golden | `tui/internal/screens/*_test.go` | `go -C tui test ./internal/screens/` | Rendered layout text matches a committed golden. |
| `app.Model` + httptest | `tui/internal/screens/*_test.go` (`http_integration_test.go`, `lifecycle_test.go`) | `go -C tui test ./...` | In-process model logic against a fake REST backend; fast, no terminal. |
| **Real-binary E2E** | `tui/internal/tuitest/` (`//go:build e2e`) + `cmd/tui-drive` | `go -C tui test ./internal/tuitest/ -tags e2e` | The **compiled** binary spawned in a real PTY (ConPTY/unix), driven by keystrokes, asserted via the captured grid. See [`tui-e2e/SKILL.md`](../skills/tui-e2e/SKILL.md). |

> [!IMPORTANT]
> **TUI runtime behavior is proven by a real-binary E2E test, not by eyeballing or `browser_subagent`** (which cannot launch a terminal app) — the TUI analog of the GUI "write an E2E test" rule. See emerging standard **G39**.

## Tools

| Layer | Tool | Command |
|-------|------|---------|
| Python unit | pytest | `pytest tests/unit/` |
| Python integration | pytest + in-memory SQLite | `pytest tests/integration/` |
| Python E2E | pytest + TestClient | `pytest tests/e2e/` |
| TypeScript unit | vitest | `npx vitest run` |
| React components | React Testing Library | `npx vitest run` |
| UI E2E | Playwright | `npx playwright test` |
| Type check (Python) | pyright | `pyright packages/` |
| Type check (TS) | tsc | `npx tsc --noEmit` |
| Lint (Python) | ruff | `ruff check packages/` |
| Lint (TS) | eslint | `cd <ts-package> && npx eslint src/ --max-warnings 0` |

## Coverage Targets (Advisory)

| Package | Target | Rationale |
|---------|--------|-----------|
| `packages/core` | 80–90% | Pure logic, easy to test, bugs are costly |
| `packages/infrastructure` | 70% | Integration tests cover critical paths |
| `packages/api` | 70% | Endpoint + error path tests |
| `ui/` | 50–60% | Focus on logic-heavy components |
| `mcp-server/` | 70% | Tool handlers must be robust |

```bash
# Check coverage (advisory — does not block)
pytest --cov=packages/core --cov-report=term
```

## TDD Workflow

1. **Implementation agent writes the test first** — defines the executable specification
2. **Implementation agent implements the code** — makes the test pass
3. **Run tests** — verify green
4. **The implementation agent NEVER modifies tests** to make them pass
5. **Run the MEU validation gate** — PROFILE D6_ADOPTER_ARGV
6. **Repeat** for next feature

## Fixtures

### In-Memory SQLite (Integration Tests)

```python
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from {{PROJECT_NAME}}_infra.database.models import Base

@pytest.fixture
def session():
    """In-memory SQLite for fast integration tests."""
    engine = create_engine("sqlite://", echo=False)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
```

### TestClient (API E2E)

```python
from fastapi.testclient import TestClient
from {{PROJECT_NAME}}_api.main import app

@pytest.fixture
def client():
    return TestClient(app)
```

## Test File Organization

```
tests/
├── unit/
│   ├── test_calculator.py        # PositionSizeCalculator
│   ├── test_entities.py          # Domain entity validation
│   └── test_value_objects.py     # Enums, value types
├── integration/
│   ├── test_repositories.py      # SQLAlchemy repos + real DB
│   └── test_unit_of_work.py      # Transaction management
└── e2e/
    └── test_api_endpoints.py     # FastAPI TestClient
```

## What to Test (per entity)

| Entity | Unit Tests | Integration Tests |
|--------|-----------|-------------------|
| Trade | Validation, field defaults | Save, get, list, exists |
| Account | Validation, type check | Save, get, list |
| ImageAttachment | Mime type, owner fields | Save, get_for_trade, delete |
| Calculator | Basic calc, edge cases, zero inputs | N/A (pure function) |
| UnitOfWork | N/A | Commit, rollback, context manager |

## Write-Boundary Test Matrix

For any MEU touching API/MCP/UI/config write paths, include these test categories:

| Test Category | Example | Required? |
|--------------|---------|-----------|
| Valid create | Happy path with all required fields | Yes |
| Valid update | Partial update with valid fields | Yes |
| Invalid enum | `account_type="INVALID"` → 422 | Yes |
| Blank required field | `name=""` or `ticker=""` → 422 | Yes |
| Malformed format | Invalid cron, invalid email, invalid URL → 422 | Yes (when applicable) |
| Non-positive/OOR numeric | `quantity=-1`, `price=0` → 422 | Yes (when applicable) |
| Extra/unexpected field | `{"valid_field": "x", "hacker_field": "y"}` → 422 | Yes (when `extra="forbid"`) |
| Missing-entity mapping | Update non-existent ID → 404 | Yes |
| Create/update parity | Update bypasses create invariant → same error | Yes |


---

## Validation pipeline & testing requirements (relocated from AGENTS.md, 2026-06-13)


## Validation Pipeline

Register static, targeted, full and optional runtime checks in PROFILE D6 and commands.md.
Each entry names argv or manual procedure, cwd, explicit scope, blocking/advisory status,
expected outcome, shell, evidence.v1 output and an input-identity procedure.

Run cheap static checks then affected targeted checks. Include shared fixtures, build/test
configuration and generated inputs in scope. Record later stages as not_run after blocking
failure. Before final implementation review, run one fresh full gate against the final
review inputs; preserve exact status/output in the handoff. Partial/cached/snapshot-only
results never satisfy full. A changed or unproven state requires rerun. Intermediate reuse
requires complete matching code/test/config/environment/external-input identity and an
implemented adapter; no snapshot/lease/reuse mechanism ships by default.

PROFILE D6 chooses integration selection, coverage policy, timing thresholds and supported
runtime surfaces. Never import source-product package prefixes or numeric budgets blindly.
Non-software validation uses actual observer/procedure/outcome evidence. Test fixtures may
use temp directories, but never set a cleanup root such as pytest --basetemp to the shared
receipt or durable artifact root.

For a full evidence shape/identity check, use tools/durable_evidence.py with --require-full
and an independently obtained --expected-state. This cannot prove execution truth or
calculate the adopter's identity; independent review still validates claims.

## Testing Requirements

### Testing Decision Framework

When implementing a new feature or bug fix, select test categories by dependency layer:

| Layer | Required Tests | Optional Tests |
|-------|---------------|----------------|
| **Domain** (entities, VOs, calculator) | Unit tests (IR-5 compliant) | Hypothesis property-based |
| **Infrastructure** (repos, UoW, encryption) | Unit + repository contract tests | Encryption verify |
| **Service** (services, validators) | Unit + integration tests | Property-based invariants |
| **API** (routes, middleware) | Unit + OpenAPI contract tests | Schemathesis fuzzing |
| **MCP** (tools, server) | Protocol + adversarial tests | Schema validation |
| **GUI** (React components) | Vitest unit + E2E wave tests | Axe-core accessibility |

### Test Naming Convention

```
tests/
├── unit/          # Isolated tests, mocked dependencies
├── integration/   # Real database, cross-layer
├── security/      # Encryption, log redaction audit
├── property/      # Hypothesis property-based invariants
├── contract/      # OpenAPI + repository contract
└── e2e/           # Playwright Electron (in ui/tests/e2e/)
```

### Coverage Expectations

Choose and document coverage floors in D6 for the project's risks/layers. A bug fix gets a
regression test first; routes/interfaces need meaningful boundary contract coverage. No
90%/80% floor is imposed on unrelated adopters.

### Runtime activation

Activate GUI/TUI/integration checks as their real runtime surfaces are delivered. Tests
must be written and wired; build bundles before testing compiled outputs. Display/PTY or
dependency errors need an actual command/nonzero exit/diagnostic and durable CI follow-up
under the shared B-row contract. Whether unresolved runtime coverage blocks release is
the declared D6/human decision, not a blanket sandbox exemption. See the applicable E2E
skill; source-product wave IDs and “delivered” states are not portable project facts.
