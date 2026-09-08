# Testing Strategy — {{PROJECT_NAME_TITLE}}

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
5. **Run the MEU validation gate** — `uv run python tools/validate_codebase.py --scope meu`
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

**MEU gate** (active implementation work): `uv run python tools/validate_codebase.py --scope meu`
**Phase gate** (only after all MEUs in a phase are complete): `uv run python tools/validate_codebase.py`

**Blocking checks** apply by scaffold and phase:
- Current scaffold: `pyright`, `ruff`, `pytest`
- When TypeScript packages are scaffolded: `tsc --noEmit`, `eslint`, `vitest`, `npm run build`

**Advisory** (report only): `pytest --cov`, `bandit`, `pip-audit`, `semgrep`.
See `.agent/skills/quality-gate/SKILL.md` for scope selection and skipped-check behavior.

> [!TIP]
> **Check what your gate actually type-checks.** A common and near-invisible failure: the
> phase/full type-check pass targets only the *product* package tree, while the pre-commit
> hook runs on **all staged** files. Type errors in `tests/` and tooling then accumulate
> through MEU work and surface in a heap at commit time, long after the gate reported green.
> Decide explicitly which trees the gate covers, make the gate and the hook agree, and write
> the chosen scope down here — so "the MEU gate is green" is unambiguous.


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

- **New domain code**: ≥ 90% branch coverage
- **New service code**: ≥ 80% branch coverage
- **New API routes**: ≥ 1 contract test per route + unit tests
- **New GUI pages**: E2E wave tests + axe-core scan (see `docs/build-plan/06-gui.md` §E2E Waves)
- **Bug fixes**: Add regression test before fixing

### E2E Wave Activation

E2E tests activate incrementally as GUI pages are built. When implementing a GUI MEU, check `ui/tests/e2e/test-ids.ts` for required `data-testid` attributes and ensure the wave's tests are **written and wired** (test-ids registered, behavior assertions present). E2E *execution* is environment-dependent: Electron needs a display, so E2E may fail to launch in the agent/reviewer sandbox ("Process failed to launch"). When it cannot run locally, mark the run `[B]` with a linked CI follow-up (Linux `xvfb-run`, or `windows-latest` native display) — an un-run E2E is **not** a completion blocker until the CI runner exists. See `docs/build-plan/06-gui.md` §E2E Waves and known-issue `E2E-SANDBOX-NODISPLAY`.

### TUI E2E Wave Activation

Real-binary TUI E2E tests (`tui/internal/tuitest/`, `//go:build e2e`) activate incrementally as each screen's lifecycle wiring lands — the same wave discipline as the GUI, with a **lower** environment bar (headless; no display server needed). The MEU-344 harness, the [`tui-e2e/SKILL.md`](../skills/tui-e2e/SKILL.md) skill, and the HOME round-trip seed test are what make the later waves writable.

| Wave | Gate MEU | E2E target | Status |
|:----:|----------|------------|:------:|
| R0-E2E | **MEU-344** `tui-e2e-harness` | Harness + HOME round-trip seed (`e2e_home_test.go`) | ✅ delivered |
| 1 | MEU-340 `tui-blotter-interactions` | Blotter cursor/pagination/sort/detail keystroke round-trips | activate when wired |
| 2 | MEU-341 `tui-portfolio` | Portfolio screen zones + navigation | activate when wired |
| 3 | MEU-342 `tui-forms` | Quick-entry / form field interactions | activate when wired |
| — | MEU-343 `tui-design-contract` | Full 5-screen design-contract suite (consumes the MEU-344 harness, **not** teatest) | activate when 340–342 land |

When implementing a screen's lifecycle MEU, add its real-binary E2E in `tuitest/` behind the `e2e` tag and tick its row. If a restricted sandbox blocks ConPTY/PTY syscalls, mark the **run** `[B]` with the pasted error + a CI follow-up in your own workflow file (ubuntu + windows; this framework ships no `.github/workflows/`, so the path is yours to create) — the test stays written and wired (`E2E-SANDBOX-NODISPLAY` precedent, lower bar). See [`tui-e2e/SKILL.md`](../skills/tui-e2e/SKILL.md).
