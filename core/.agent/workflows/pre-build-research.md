---
description: Research-before-build workflow — scan GitHub repos, extract patterns, and create AI instruction sets before implementing any feature
---

# Pre-Build Research Workflow

> **Primary role:** `.agent/roles/researcher.md`
>
> **Orchestration context:** `.agent/workflows/orchestrated-delivery.md`

> **Rule**: No feature implementation begins until this workflow is complete. The output is a research brief that either (a) provides reference code/patterns for the AI to use as instruction sets, or (b) confirms no prior art exists and the feature must be built from scratch.
>
> **Trigger:** Use this workflow whenever the build plan or local canonical docs are not specific enough to support a complete implementation, or when current best practice must be confirmed before writing acceptance criteria.
>
> **Research order:** (1) local canonical docs, (2) official docs / standards / primary sources via web search, (3) high-quality reference implementations.

## Why This Exists

Instead of writing rigid code for every variation of a problem (e.g., 50 broker CSV parsers), we teach the AI the *pattern* of solving it by gathering reference implementations. This turns engineering problems into agentic AI problems — the AI dynamically adapts using examples rather than hardcoded logic.

---

## Step 1: Define the Feature Scope

Write a 2-3 sentence description of the feature you're about to build. Be specific about:

- **What data** does it consume / produce?
- **What variations** exist (e.g., different broker formats, different calculation methods)?
- **What's the happy path** vs edge cases?

Save this to: `docs/research/{feature-slug}/scope.md`

---

## Step 2: Identify Sources to Scan

Search authoritative sources in this order. Use these strategies:

```text
# Strategy 1: Official docs / standards / primary sources
# Use `search_web` (preferred) or an equivalent primary-source web search tool
query: "{feature name} official docs standards best practices"
engine: brave
count: 10

# Strategy 2: Direct GitHub / reference implementation search
query: "github {feature name} {language} open source"
engine: brave
count: 10

# Strategy 3: Known project repos (check these first)
# See the reference table below for feature → repo mappings

# Strategy 4: Awesome lists
query: "awesome {domain} github list"
engine: brave
count: 5
```

If local docs and primary sources fully resolve the behavior, GitHub repo scanning is optional rather than mandatory.

### Known Feature → Repo Reference Table

| Feature Area | Repos to Check | What to Extract |
|---|---|---|
| **Trade import adapters** | [Deltalytix](https://github.com/hugodemenez/deltalytix), [TradeNote](https://github.com/Eleven-Trading/TradeNote), [Tradervue API](https://github.com/tradervue) | CSV column mappings, field normalization, broker-specific quirks |
| **Position size calculators** | TradeLogger (local `p:\TradeLogger`), open-source risk calc repos | Formulas, input validation, edge cases (fractional shares, options) |
| **Wash sale detection** | Tax-loss harvesting libraries, IRS rule implementations | 30-day window logic, substantially identical security matching |
| **IBKR API integration** | [ib_insync](https://github.com/erdewit/ib_insync), [ibapi](https://github.com/InteractiveBrokers/tws-api) | Connection lifecycle, data request patterns, error handling |
| **SQLCipher + Electron** | [Signal Desktop](https://github.com/signalapp/Signal-Desktop) | Encryption key management, migration patterns, IPC security |
| **Calendar trade views** | [AI Trading Journal](https://github.com/Bilovodskyi/ai-trading-journal) | Calendar component, day-cell rendering, trade aggregation |
| **AI trade analysis** | [Deltalytix AI endpoints](https://github.com/hugodemenez/deltalytix) | Prompt templates, analysis chains, insight categorization |
| **Trade plan templates** | Trading plan repos, strategy template collections | Plan structure, required fields, conviction scoring |

---

## Step 3: Extract Patterns & Schema Mappings

For each relevant repo found, extract:

### 3a. Schema Mappings (for data import/export features)
```
# Read the repo's data models / types / interfaces
# Save field-by-field mapping:
#   Source field → Target field → Transform logic → Edge cases
```

### 3b. Algorithm / Logic Patterns (for calculation features)
```
# Extract the core algorithm as pseudocode
# Note: input validation rules, boundary conditions, error handling
```

### 3c. API Interaction Patterns (for integration features)
```
# Extract: authentication flow, request/response schemas,
# rate limiting, error codes, retry strategies
```

Save extracted patterns to: `docs/research/{feature-slug}/patterns.md`


---

## Step 4: Create AI Instruction Set

Transform the extracted patterns into a prompt instruction set that the AI (via MCP) can use at runtime. This is the key step — you're teaching the AI HOW to solve the problem dynamically.

### Template: `docs/research/{feature-slug}/ai-instructions.md`

```markdown
# AI Instruction Set: {Feature Name}

## Task
{What the AI should accomplish}

## Reference Examples
{3-5 examples extracted from GitHub repos showing input → output mappings}

## Schema
{Target {{PROJECT_NAME_TITLE}} schema the output must conform to}

## Edge Cases
{Known edge cases from reference implementations}

## Validation Rules
{How to verify the output is correct}
```

**A filled-in example.** The domain below is the originating repo's (broker trade
import), kept concrete on purpose: the point of the artifact is that vague reference
examples produce vague normalizers, and a generic "widget importer" would not show
that. Read it for the *shape* — task, several real input/output pairs from real
sources, target schema, edge cases harvested from those sources, and checkable
validation rules — then write yours against your own domain.

```markdown
# AI Instruction Set: Trade Import Normalization

## Task
Given a CSV/JSON file from any broker, normalize each trade into the project's
TradeRecord schema.

## Reference Examples
### Example 1: Interactive Brokers (from ib_insync)
Input:  DateTime,Symbol,Action,Quantity,Price,Commission
        2026-01-15 09:31:00,AAPL,BOT,100,195.50,1.00
Output: { date: "2026-01-15T09:31:00", ticker: "AAPL", side: "BUY",
          qty: 100, price: 195.50, fees: 1.00, broker: "IBKR" }

### Example 2: TradesViz Export (from Deltalytix)
Input:  Date,Stock,Type,Shares,Entry Price,Exit Price
        01/15/2026,AAPL,Long,100,195.50,198.00
Output: { date: "2026-01-15", ticker: "AAPL", side: "BUY",
          qty: 100, price: 195.50, fees: null, broker: "TradesViz" }

## Schema
{ date: ISO8601, ticker: string, side: "BUY"|"SELL",
  qty: number, price: number, fees: number|null,
  broker: string, notes: string|null }

## Edge Cases
- Partial fills: multiple rows same order ID → group by order_id
- Options: symbol format varies (AAPL 240119C00195000 vs AAPL Jan24 195 Call)
- Forex: pair notation (EUR/USD vs EURUSD)
- Crypto: fractional quantities (0.00142 BTC)

## Validation Rules
- date must parse to valid ISO8601
- qty must be > 0
- price must be > 0
- side must be BUY or SELL (normalize: BOT→BUY, SLD→SELL, Long→BUY, Short→SELL)
```

---

## Step 5: Build Decision — Code vs AI

Based on the research, decide which approach to use:

| Scenario | Approach |
|---|---|
| **5+ reference implementations exist** | AI-driven: feed instruction set via MCP, let AI dynamically adapt |
| **1-4 reference implementations** | Hybrid: build core logic from patterns, use AI for edge cases |
| **No prior art found** | Code-first: build from scratch, then create instruction set for future AI enhancement |
| **Security-critical feature** | Code-first with AI review: never let AI handle encryption/auth logic directly |

Document the decision in: `docs/research/{feature-slug}/decision.md`

---

## Step 6: Save Research Brief

Create the final research brief summarizing all findings:

Persist the final research brief to `docs/research/{feature-slug}/`.

### Research Brief Checklist

- [ ] Feature scope defined (`scope.md`)
- [ ] GitHub repos scanned (minimum 3 searches)
- [ ] Patterns extracted (`patterns.md`)
- [ ] AI instruction set created (`ai-instructions.md`)
- [ ] Build decision documented (`decision.md`)

---

## Output

After completing this workflow, you should have:

```
docs/research/{feature-slug}/
├── scope.md              # What we're building
├── patterns.md           # What we found in existing repos
├── ai-instructions.md    # Teaching the AI how to solve it
└── decision.md           # Code vs AI vs Hybrid approach
```

**Only after all files exist should feature implementation begin.**
