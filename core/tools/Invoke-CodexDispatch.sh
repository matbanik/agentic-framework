#!/usr/bin/env bash
# Invoke-CodexDispatch.sh — POSIX/macOS companion to Invoke-CodexDispatch.ps1
#
# Same dispatch contract: mode/sandbox mapping, version gate, path containment,
# timeout + process-tree cleanup, receipt/status artifacts, optional schema check.
# Prefer this on macOS/Linux when pwsh is unavailable; otherwise either wrapper is valid.
#
# Placeholders (filled by scripts/instantiate.py):
#   {{RECEIPTS_DIR}}  {{PROJECT_ROOT}}  {{PROJECT_NAME_UPPER}}
#
set -u
set -o pipefail

SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
# Sibling helpers are resolved against THIS file, not the working directory: the working
# directory is the tree under review, which for a read-only review is not the tree this
# wrapper was installed into.
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

MODE="ReviewReadOnly"
REASONING_EFFORT="high"
RETENTION="CompressOnSuccess"
MODEL=""
MODEL_GIVEN=0
MODEL_CLASS="independent_reviewer"
AUTHOR_VENDOR="${{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR:-}"
PROMPT_FILE=""
PROMPT_TEXT=""
DISPATCH_ID=""
# Review-loop bound. Exactly one of --LoopId / --NonReviewDispatch is required;
# see the gate below and .agent/docs/verification-principles.md V41/V43.
LOOP_ID=""
NON_REVIEW_DISPATCH=0
GATE_ONLY=0
LEDGER_GATE_RESULT="not-applicable"
# Which kind of review this is. An assertion, not a source: with --LoopId the kind comes
# from the mode the ledger recorded at `begin`, and a --Kind that disagrees is exit 1.
KIND=""
LEDGER_MODE=""
DISPATCH_KIND=""
TIMEOUT_FLOOR_APPLIED=0
OUTPUT_DIR="{{RECEIPTS_DIR}}/dispatch"
OUTPUT_SCHEMA=""
USE_SEARCH=0
FORCE=0
FULL_ACCESS_JUSTIFICATION=""
API_KEY_ENV_VAR=""
WORKING_DIRECTORY="{{PROJECT_ROOT}}"
CODEX_EXECUTABLE="codex"
BENCHMARK_ISOLATION=0
BENCHMARK_CONTEXT_RECEIPT=""
BENCHMARK_CONTEXT_SHA256=""
TIMEOUT_SEC=0
POST_KILL_GRACE_SEC=90
NO_PROCESS_TREE_KILL=0
MIN_CODEX_CLI_VERSION="0.145.0"
SKIP_CODEX_VERSION_CHECK=0

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: Invoke-CodexDispatch.sh [options]

Mirrors tools/Invoke-CodexDispatch.ps1 for macOS/Linux (bash).

Required (exactly one):
  --PromptFile PATH | --PromptText TEXT

Required (exactly one) -- the review-loop bound:
  --LoopId ID               Bind this dispatch to a review loop. review_ledger.py
                            is consulted before dispatching; if it refuses, this
                            script exits 9 without spending anything.
  --NonReviewDispatch       Declare that this is not an independent review, so no
                            round is consumed. Recorded in status.json.

Common:
  --Mode ReviewReadOnly|ReviewWorkspace|FullAccess
  --ReasoningEffort medium|high|xhigh|max
  --Retention Keep|CompressOnSuccess|DeleteOnSuccess
  --Model NAME              (optional; omit to resolve -ModelClass from the registry)
  --ModelClass NAME         (default: independent_reviewer)
  --AuthorVendor VENDOR     (required for vendor_distinct_from: author;
                             defaults to ${{{PROJECT_NAME_UPPER}}_AUTHOR_VENDOR},
                             the same variable Invoke-CodexDispatch.ps1 reads)
  --DispatchId ID
  --OutputDir PATH          (must stay under {{RECEIPTS_DIR}})
  --OutputSchema PATH
  --WorkingDirectory PATH   (must stay under {{PROJECT_ROOT}})
  --CodexExecutable PATH|NAME
  --FullAccessJustification TEXT   (required for FullAccess; ≥20 non-ws chars)
  --ApiKeyEnvVar NAME
  --Kind plan|execution|discovery|handoff|multi-handoff
                            Assert the kind of review. Optional: with --LoopId the
                            kind is read from the loop's recorded mode, and a --Kind
                            that disagrees is exit 1. `execution` and `multi-handoff`
                            carry a 2700s timeout floor.
  --TimeoutSec N            (0 = derive from ReasoningEffort, then raise to the
                             floor for this dispatch kind if there is one)
  --PostKillGraceSec N
  --MinCodexCliVersion x.y.z
  --UseSearch
  --Force
  --GateOnly                Consult the ledger and exit without dispatching.
  --NoProcessTreeKill
  --SkipCodexVersionCheck
  --BenchmarkIsolation
  --BenchmarkContextReceipt PATH
  --BenchmarkContextSha256 HEX64

Exit codes:
  0  dispatch completed (or --GateOnly and a round is permitted)
  1  bad invocation / validation refused
  3  something could not be checked -- missing python3, absent review_ledger.py,
     or a dispatch failure. Never treat 3 as a pass.
  9  the review ledger refused this round. A decision, not an error: apply the
     specific relief its message names, or escalate. Kept distinct from 1 and 3
     because "the loop is over" and "the tool broke" call for opposite responses.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --Mode) MODE="${2:-}"; shift 2 ;;
    --ReasoningEffort) REASONING_EFFORT="${2:-}"; shift 2 ;;
    --Retention) RETENTION="${2:-}"; shift 2 ;;
    --Model) MODEL="${2:-}"; MODEL_GIVEN=1; shift 2 ;;
    --ModelClass) MODEL_CLASS="${2:-}"; shift 2 ;;
    --AuthorVendor) AUTHOR_VENDOR="${2:-}"; shift 2 ;;
    --PromptFile) PROMPT_FILE="${2:-}"; shift 2 ;;
    --PromptText) PROMPT_TEXT="${2:-}"; shift 2 ;;
    --DispatchId) DISPATCH_ID="${2:-}"; shift 2 ;;
    --LoopId) LOOP_ID="${2:-}"; shift 2 ;;
    --NonReviewDispatch) NON_REVIEW_DISPATCH=1; shift ;;
    --GateOnly) GATE_ONLY=1; shift ;;
    --Kind) KIND="${2:-}"; shift 2 ;;
    --OutputDir) OUTPUT_DIR="${2:-}"; shift 2 ;;
    --OutputSchema) OUTPUT_SCHEMA="${2:-}"; shift 2 ;;
    --FullAccessJustification) FULL_ACCESS_JUSTIFICATION="${2:-}"; shift 2 ;;
    --ApiKeyEnvVar) API_KEY_ENV_VAR="${2:-}"; shift 2 ;;
    --WorkingDirectory) WORKING_DIRECTORY="${2:-}"; shift 2 ;;
    --CodexExecutable) CODEX_EXECUTABLE="${2:-}"; shift 2 ;;
    --BenchmarkContextReceipt) BENCHMARK_CONTEXT_RECEIPT="${2:-}"; shift 2 ;;
    --BenchmarkContextSha256) BENCHMARK_CONTEXT_SHA256="${2:-}"; shift 2 ;;
    --TimeoutSec) TIMEOUT_SEC="${2:-}"; shift 2 ;;
    --PostKillGraceSec) POST_KILL_GRACE_SEC="${2:-}"; shift 2 ;;
    --MinCodexCliVersion) MIN_CODEX_CLI_VERSION="${2:-}"; shift 2 ;;
    --UseSearch) USE_SEARCH=1; shift ;;
    --Force) FORCE=1; shift ;;
    --NoProcessTreeKill) NO_PROCESS_TREE_KILL=1; shift ;;
    --SkipCodexVersionCheck) SKIP_CODEX_VERSION_CHECK=1; shift ;;
    --BenchmarkIsolation) BENCHMARK_ISOLATION=1; shift ;;
    *) die "Unknown argument: $1 (see --help)" ;;
  esac
done

# --- helpers -----------------------------------------------------------------

sha256_file() {
  local path="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$path"
  fi
}

physical_path() {
  local path="$1"
  python3 -c 'import os,sys; print(os.path.realpath(os.path.abspath(sys.argv[1])).replace("\\\\","/"))' "$path"
}

path_under() {
  # path_under CHILD PARENT  → 0 if CHILD == PARENT or CHILD starts with PARENT/
  local child="$1" parent="$2"
  [[ "$child" == "$parent" || "$child" == "$parent"/* ]]
}

default_timeout() {
  case "$1" in
    medium) echo 900 ;;
    high) echo 1800 ;;
    xhigh) echo 2700 ;;
    max) echo 3600 ;;
    *) echo 900 ;;
  esac
}

kind_timeout_floor() {
  # A floor, not a default, and the twin of Get-KindTimeoutFloorSec in the .ps1: the
  # effort tier says how hard the model thinks, which is a different question from how
  # much material it has to read. An execution review reads the whole change plus its
  # receipts, so a `medium` one inherits 900s and dies mid-verdict -- and the round is
  # spent either way, because the ledger counts a dispatch it permitted.
  # 0 means this kind has nothing to say about the timeout; the effort default stands.
  case "$1" in
    execution) echo 2700 ;;
    multi-handoff) echo 2700 ;;
    *) echo 0 ;;
  esac
}

parse_semver() {
  # stdout: major minor patch as space-separated ints; empty if unparsable
  local text="$1"
  if [[ "$text" =~ ([0-9]+)\.([0-9]+)\.([0-9]+) ]]; then
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]} ${BASH_REMATCH[3]}"
  fi
}

semver_lt() {
  # semver_lt "a b c" "d e f" → 0 if a.b.c < d.e.f
  local a=($1) b=($2)
  (( ${#a[@]} == 3 && ${#b[@]} == 3 )) || return 1
  if (( a[0] < b[0] )); then return 0; fi
  if (( a[0] > b[0] )); then return 1; fi
  if (( a[1] < b[1] )); then return 0; fi
  if (( a[1] > b[1] )); then return 1; fi
  if (( a[2] < b[2] )); then return 0; fi
  return 1
}

stop_process_tree() {
  local pid="$1"
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  if [[ "$NO_PROCESS_TREE_KILL" -eq 0 ]]; then
    # Prefer process-group kill when the child was started in its own group.
    local pgid
    pgid="$(ps -o pgid= -p "$pid" 2>/dev/null | tr -d ' ' || true)"
    if [[ -n "$pgid" && "$pgid" != "0" && "$pgid" != "1" ]]; then
      kill -TERM -- "-$pgid" 2>/dev/null || true
      sleep 0.5
      kill -KILL -- "-$pgid" 2>/dev/null || true
    fi
    if command -v pkill >/dev/null 2>&1; then
      pkill -TERM -P "$pid" 2>/dev/null || true
      sleep 0.2
      pkill -KILL -P "$pid" 2>/dev/null || true
    fi
  fi
  kill -TERM "$pid" 2>/dev/null || true
  sleep 0.2
  kill -KILL "$pid" 2>/dev/null || true
}

events_have_terminal() {
  local events_path="$1"
  [[ -f "$events_path" ]] || return 1
  grep -E '"type"[[:space:]]*:[[:space:]]*"(turn\.completed|turn\.failed)"' "$events_path" >/dev/null 2>&1
}

terminal_and_final_ready() {
  local events_path="$1" final_path="$2"
  events_have_terminal "$events_path" || return 1
  [[ -f "$final_path" && -s "$final_path" ]]
}

# --- validation --------------------------------------------------------------

case "$MODE" in
  ReviewReadOnly|ReviewWorkspace|FullAccess) ;;
  *) die "Invalid Mode '$MODE' (expected ReviewReadOnly|ReviewWorkspace|FullAccess)." ;;
esac
case "$REASONING_EFFORT" in
  medium|high|xhigh|max) ;;
  *) die "Invalid ReasoningEffort '$REASONING_EFFORT'." ;;
esac
case "$RETENTION" in
  Keep|CompressOnSuccess|DeleteOnSuccess) ;;
  *) die "Invalid Retention '$RETENTION'." ;;
esac

if [[ -z "$PROMPT_TEXT" && -z "$PROMPT_FILE" ]]; then
  die "Either --PromptText or --PromptFile must be specified."
fi
if [[ -n "$PROMPT_TEXT" && -n "$PROMPT_FILE" ]]; then
  die "Cannot specify both --PromptText and --PromptFile."
fi
# --- review-loop bound -------------------------------------------------------
# Mirrors the same block in Invoke-CodexDispatch.ps1. It runs before the version
# preflight and the long exec on purpose: the cheapest moment to refuse a round
# is before it costs anything.
if [[ -n "$LOOP_ID" && "$NON_REVIEW_DISPATCH" -eq 1 ]]; then
  die "Specify --LoopId or --NonReviewDispatch, not both. A dispatch is either bound to a review loop or declared not to be one."
fi
if [[ -z "$LOOP_ID" && "$NON_REVIEW_DISPATCH" -eq 0 ]]; then
  die "loop_id_required: pass --LoopId <id> to bind this dispatch to a review loop, or --NonReviewDispatch if it is not an independent review. There is no default: an unbound review dispatch is an unbounded review loop, and a forgotten flag would be indistinguishable from a deliberate one."
fi
if [[ -n "$LOOP_ID" && ! "$LOOP_ID" =~ ^[a-z0-9][a-z0-9._-]{0,127}$ ]]; then
  die "Invalid LoopId format. Must match ^[a-z0-9][a-z0-9._-]{0,127}\$ -- the same pattern review_ledger.py and review-verdict.schema.v2.json enforce, so an id accepted here is accepted there."
fi
# The vocabulary is review_ledger.py's ROUND_BUDGETS keys, not a second list of names:
# the .ps1 twin spells the same set in a ValidateSet, and bash has no such thing, so the
# check is explicit here rather than absent.
if [[ -n "$KIND" ]]; then
  case "$KIND" in
    plan|execution|discovery|handoff|multi-handoff) ;;
    *) die "Invalid Kind '$KIND'. Expected one of plan, execution, discovery, handoff, multi-handoff -- the modes review_ledger.py accepts at \`begin\`." ;;
  esac
fi
if [[ -n "$KIND" && "$NON_REVIEW_DISPATCH" -eq 1 ]]; then
  die "kind_not_applicable: --Kind names the kind of *review* this is, and --NonReviewDispatch says this is not a review. Drop one. Ignoring the flag instead would leave a receipt claiming a review kind for a dispatch that consumed no round."
fi

if [[ -n "$LOOP_ID" ]]; then
  LEDGER_SCRIPT="$(dirname "$SCRIPT_PATH")/review_ledger.py"
  if [[ ! -f "$LEDGER_SCRIPT" ]]; then
    printf '%s\n' "ledger_unavailable: --LoopId was given but review_ledger.py is not present at $LEDGER_SCRIPT, so the round budget could not be checked. This is exit 3, not a pass: 'could not check' is not 'checked and permitted' (V5/V31). Restore the tool, or pass --NonReviewDispatch if this dispatch is genuinely not a review." >&2
    exit 3
  fi
  LEDGER_PYTHON=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then LEDGER_PYTHON="$candidate"; break; fi
  done
  if [[ -z "$LEDGER_PYTHON" ]]; then
    printf '%s\n' "ledger_unavailable: neither python3 nor python is on PATH, so review_ledger.py could not run and the round budget was not checked. Exit 3, not a pass. Install Python 3, or pass --NonReviewDispatch." >&2
    exit 3
  fi

  # `set +e` around the call: this script runs under `set -e`, which would abort
  # on the ledger's non-zero exit before the exit status could be inspected --
  # turning a REFUSE (a decision that must be reported as exit 9) into an
  # unexplained abort.
  set +e
  LEDGER_OUTPUT="$("$LEDGER_PYTHON" "$LEDGER_SCRIPT" evaluate --loop-id "$LOOP_ID" 2>&1)"
  LEDGER_EXIT=$?
  set -e

  case "$LEDGER_EXIT" in
    0)
      LEDGER_GATE_RESULT="permitted"
      printf '[ledger] %s\n' "$LEDGER_OUTPUT"
      if [[ "$LEDGER_OUTPUT" =~ mode=([a-z0-9][a-z0-9-]*) ]]; then
        LEDGER_MODE="${BASH_REMATCH[1]}"
      fi
      if [[ -z "$LEDGER_MODE" ]]; then
        # 3, not a shrug: the mode is where the dispatch kind comes from, and the kind is
        # what raises the timeout floor. Guessing would hand an execution review the
        # 15-minute default -- the silent failure the floor exists to prevent.
        printf '%s\n' "ledger_mode_unavailable: review_ledger.py permitted the round but its output did not name the loop's mode (expected 'mode=<plan|execution|discovery|handoff|multi-handoff>' on the OK line). The wrapper and the ledger ship as a pair; a ledger old enough to omit it is a mismatched pair, not a pass. Update tools/review_ledger.py." >&2
        exit 3
      fi
      ;;
    1)
      printf '%s\n' "$LEDGER_OUTPUT" >&2
      printf '%s\n' "[ledger] refused loop '$LOOP_ID'. Not dispatching. Escalate to a human, or apply the specific relief the message names -- do not re-run with --NonReviewDispatch to get past this." >&2
      exit 9
      ;;
    *)
      printf '%s\n' "$LEDGER_OUTPUT" >&2
      printf '%s\n' "[ledger] could not evaluate loop '$LOOP_ID' (review_ledger.py exit $LEDGER_EXIT). Failing closed." >&2
      exit 3
      ;;
  esac
else
  LEDGER_GATE_RESULT="bypassed-non-review"
  printf '%s\n' "[ledger] --NonReviewDispatch: no round consumed, no loop bound."
fi

# --- dispatch kind + the timeout floor it implies -----------------------------
# Resolved before --GateOnly returns so the floor is visible without paying for a
# dispatch, and so a --Kind that disagrees with the ledger costs nothing to report.
if [[ -n "$LOOP_ID" ]]; then
  DISPATCH_KIND="$LEDGER_MODE"
  if [[ -n "$KIND" && "$KIND" != "$DISPATCH_KIND" ]]; then
    die "kind_mismatch: --Kind '$KIND' but loop '$LOOP_ID' was opened with mode '$DISPATCH_KIND'. The ledger wins, and the disagreement is exit 1 rather than a silent correction: it usually means this dispatch is aimed at the wrong loop, and that loop's budget is the one being spent."
  fi
else
  DISPATCH_KIND="non-review"
fi

KIND_FLOOR_SEC="$(kind_timeout_floor "$DISPATCH_KIND")"
if [[ "$TIMEOUT_SEC" -le 0 ]]; then
  TIMEOUT_SEC="$(default_timeout "$REASONING_EFFORT")"
  if (( KIND_FLOOR_SEC > TIMEOUT_SEC )); then
    printf '%s\n' "[kind] $DISPATCH_KIND review: raising the derived --TimeoutSec from $TIMEOUT_SEC to the ${KIND_FLOOR_SEC}s floor for this kind."
    TIMEOUT_SEC="$KIND_FLOOR_SEC"
    TIMEOUT_FLOOR_APPLIED=1
  fi
elif (( KIND_FLOOR_SEC > TIMEOUT_SEC )); then
  # An explicit --TimeoutSec is the caller's decision and is honoured; there are small
  # execution reviews. But it is said out loud, because a truncated verdict looks
  # identical to a reviewer that found nothing.
  printf '%s\n' "[kind] $DISPATCH_KIND review with explicit --TimeoutSec $TIMEOUT_SEC, below the ${KIND_FLOOR_SEC}s floor for this kind. Honouring the caller. A no-terminal timeout here still spends the round."
fi
printf '%s\n' "[kind] dispatch kind '$DISPATCH_KIND', timeout ${TIMEOUT_SEC}s."

if [[ "$GATE_ONLY" -eq 1 ]]; then
  printf '%s\n' "[ledger] --GateOnly: gate result '$LEDGER_GATE_RESULT'. Exiting without dispatching."
  exit 0
fi

if [[ "$MODEL_GIVEN" -eq 1 && -z "$MODEL" ]]; then
  die "Model must be specified."
fi
if [[ "$MODEL_GIVEN" -eq 1 && ! "$MODEL" =~ ^[a-zA-Z0-9.-]+$ ]]; then
  die "Invalid Model format."
fi

resolve_python() {
  if [[ -n "${AGENT_RESOLVE_PYTHON:-}" ]]; then
    echo "${AGENT_RESOLVE_PYTHON}"
    return
  fi
  for candidate in python3 python py; do
    if command -v "${candidate}" >/dev/null 2>&1; then
      echo "${candidate}"
      return
    fi
  done
}

locate_resolver() {
  if [[ -n "${AGENT_RESOLVE_SCRIPT:-}" ]]; then
    echo "${AGENT_RESOLVE_SCRIPT}"
    return
  fi
  local candidates=()
  if [[ -n "${AGENT_MODEL_REGISTRY:-}" ]]; then
    local override="${AGENT_MODEL_REGISTRY}"
    if [[ -d "$override" ]]; then
      candidates+=("${override}/tools/resolve_model.py")
    else
      candidates+=("$(dirname "$override")/tools/resolve_model.py")
    fi
  fi
  # Shared home from env, never a baked drive letter: a literal like "P:/.agent" is one
  # machine's layout and is meaningless on macOS/Linux (.agent/INSTANTIATE.md S2).
  if [[ -n "${AGENT_MODEL_REGISTRY_HOME:-}" ]]; then
    candidates+=("${AGENT_MODEL_REGISTRY_HOME}/tools/resolve_model.py")
  fi
  if [[ -n "${USERPROFILE:-}" ]]; then
    candidates+=("${USERPROFILE}/.agent/tools/resolve_model.py")
  fi
  if [[ -n "${HOME:-}" ]]; then
    candidates+=("${HOME}/.agent/tools/resolve_model.py")
  fi
  local c
  for c in "${candidates[@]}"; do
    if [[ -f "$c" ]]; then
      echo "$c"
      return
    fi
  done
}

PYTHON_BIN="$(resolve_python)"
RESOLVER="$(locate_resolver)"
if [[ -z "${PYTHON_BIN}" ]]; then
  die "registry_not_found: no interpreter available to read the resolver"
fi
if [[ -z "${RESOLVER}" || ! -f "${RESOLVER}" ]]; then
  die "registry_not_found: no resolve_model.py at any S2 location"
fi

if [[ "$BENCHMARK_ISOLATION" -eq 1 ]]; then
  PIN_SLUG="$("${PYTHON_BIN}" -c "import json, os, pathlib, sys
candidates = []
env = os.environ.get('AGENT_MODEL_REGISTRY')
if env:
    p = pathlib.Path(env)
    candidates.append(p if p.suffix.lower() == '.json' else p / 'model-registry.json')
shared = os.environ.get('AGENT_MODEL_REGISTRY_HOME')
if shared:
    candidates.append(pathlib.Path(shared) / 'model-registry.json')
home = os.environ.get('USERPROFILE') or os.environ.get('HOME')
if home:
    candidates.append(pathlib.Path(home) / '.agent' / 'model-registry.json')
for c in candidates:
    if c.is_file():
        doc = json.loads(c.read_text(encoding='utf-8'))
        pin = (doc.get('pins') or {}).get('benchmark_headroom_baseline') or {}
        slug = pin.get('slug')
        if not slug:
            sys.exit('unknown_pin: benchmark_headroom_baseline')
        print(slug)
        break
else:
    sys.exit('registry_not_found: no compiled registry for pin lookup')
")" || die "registry_not_found: cannot read benchmark_headroom_baseline pin"
  if [[ "$MODEL_GIVEN" -eq 0 ]]; then
    MODEL="$PIN_SLUG"
  fi
else
  # --project names the repo whose overlay governs this dispatch. Both wrappers
  # dispatch the same reviews, so an overlay read by only one of them would make
  # the answer depend on which shell the caller happened to be in.
  RESOLVE_ARGS=(
    resolve "${MODEL_CLASS}"
    --harness codex-cli
    --format env
    --project "{{PROJECT_ROOT}}"
  )
  if [[ -n "${AUTHOR_VENDOR}" ]]; then
    RESOLVE_ARGS+=(--author-vendor "${AUTHOR_VENDOR}")
  fi
  if [[ "${MODEL_GIVEN}" -eq 1 ]]; then
    RESOLVE_ARGS+=(--slug "${MODEL}")
  fi
  if [[ -n "${REASONING_EFFORT}" ]]; then
    RESOLVE_ARGS+=(--effort "${REASONING_EFFORT}")
  fi
  if ! RESOLVED="$("${PYTHON_BIN}" "${RESOLVER}" "${RESOLVE_ARGS[@]}")"; then
    exit 1
  fi
  while IFS='=' read -r key value; do
    value="${value%$'\r'}"
    case "${key}" in
      AGENT_MODEL_SLUG) MODEL="${value}" ;;
      AGENT_MODEL_EFFORT) REASONING_EFFORT="${value}" ;;
    esac
  done <<< "${RESOLVED}"
  if [[ -z "$MODEL" ]]; then
    die "registry_not_found: resolver returned no slug for ${MODEL_CLASS}"
  fi
fi

RECEIPTS_ROOT="$(physical_path "{{RECEIPTS_DIR}}")"
REPO_ROOT="$(physical_path "{{PROJECT_ROOT}}")"

if [[ "$BENCHMARK_ISOLATION" -eq 1 ]]; then
  [[ "$MODE" == "ReviewReadOnly" ]] || die "BenchmarkIsolation requires Mode ReviewReadOnly."
  [[ "$REASONING_EFFORT" == "medium" ]] || die "BenchmarkIsolation requires ReasoningEffort medium."
  [[ "$MODEL" == "$PIN_SLUG" ]] || die "BenchmarkIsolation requires Model ${PIN_SLUG}."
  [[ "$USE_SEARCH" -eq 0 ]] || die "BenchmarkIsolation forbids search."
  [[ -n "$BENCHMARK_CONTEXT_RECEIPT" ]] || die "BenchmarkIsolation requires BenchmarkContextReceipt."
  [[ "$BENCHMARK_CONTEXT_SHA256" =~ ^[0-9a-f]{64}$ ]] || die "BenchmarkIsolation requires a lowercase SHA-256 context hash."
fi

if [[ -n "$DISPATCH_ID" ]]; then
  if [[ ! "$DISPATCH_ID" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$ ]]; then
    die "Invalid DispatchId format."
  fi
else
  DISPATCH_ID="dispatch-$(date -u +%Y%m%d%H%M%S)-$((RANDOM % 9000 + 1000))"
fi


if [[ "$OUTPUT_DIR" == *"*"* || "$OUTPUT_DIR" == *"?"* || "$OUTPUT_DIR" == *"["* ]]; then
  die "OutputDir must not contain wildcard characters."
fi

CANONICAL_OUTPUT_DIR="$(physical_path "$OUTPUT_DIR")"
path_under "$CANONICAL_OUTPUT_DIR" "$RECEIPTS_ROOT" || die "OutputDir must be under {{RECEIPTS_DIR}}"

if [[ "$MODE" == "FullAccess" ]]; then
  [[ -n "$FULL_ACCESS_JUSTIFICATION" ]] || die "FullAccessJustification is required when Mode is FullAccess."
  non_ws="${FULL_ACCESS_JUSTIFICATION//[[:space:]]/}"
  (( ${#non_ws} >= 20 )) || die "FullAccessJustification must be at least 20 non-whitespace characters."
fi

if [[ -n "$API_KEY_ENV_VAR" ]]; then
  [[ "$API_KEY_ENV_VAR" =~ ^[A-Z_][A-Z0-9_]*$ ]] || die "Invalid ApiKeyEnvVar format."
  [[ -n "${!API_KEY_ENV_VAR+x}" ]] || die "ApiKeyEnvVar '$API_KEY_ENV_VAR' not found in environment."
fi

CANONICAL_WORK_DIR="$(physical_path "$WORKING_DIRECTORY")"
[[ -d "$CANONICAL_WORK_DIR" ]] || die "WorkingDirectory does not exist."
path_under "$CANONICAL_WORK_DIR" "$REPO_ROOT" || die "WorkingDirectory must be under the repository root."

CANONICAL_SCHEMA=""
if [[ -n "$OUTPUT_SCHEMA" ]]; then
  CANONICAL_SCHEMA="$(physical_path "$OUTPUT_SCHEMA")"
  [[ -f "$CANONICAL_SCHEMA" ]] || die "OutputSchema file does not exist."
  path_under "$CANONICAL_SCHEMA" "$REPO_ROOT" || die "OutputSchema must be under the repository root."
fi

CANONICAL_PROMPT_FILE=""
if [[ -n "$PROMPT_FILE" ]]; then
  CANONICAL_PROMPT_FILE="$(physical_path "$PROMPT_FILE")"
  [[ -f "$CANONICAL_PROMPT_FILE" ]] || die "PromptFile does not exist."
  if ! path_under "$CANONICAL_PROMPT_FILE" "$REPO_ROOT" && ! path_under "$CANONICAL_PROMPT_FILE" "$RECEIPTS_ROOT"; then
    die "PromptFile must be under the repository root or {{RECEIPTS_DIR}}."
  fi
fi

if [[ "$BENCHMARK_ISOLATION" -eq 1 ]]; then
  bench_root="$(physical_path "{{PROJECT_ROOT}}/.benchmark-work/context-provider/provider-root")"
  bench_schema="$(physical_path "{{PROJECT_ROOT}}/.agent/schemas/headroom-standalone-answer.schema.json")"
  [[ "$CANONICAL_WORK_DIR" == "$bench_root" ]] || die "BenchmarkIsolation requires the exact provider-root working directory."
  [[ -n "$CANONICAL_SCHEMA" && "$CANONICAL_SCHEMA" == "$bench_schema" ]] || die "BenchmarkIsolation requires the exact standalone answer schema."
  bench_ctx="$(physical_path "$BENCHMARK_CONTEXT_RECEIPT")"
  [[ -f "$bench_ctx" ]] || die "BenchmarkIsolation context receipt does not exist."
  actual_sha="$(sha256_file "$bench_ctx")"
  [[ "$actual_sha" == "$BENCHMARK_CONTEXT_SHA256" ]] || die "BenchmarkIsolation context receipt hash mismatch."
  BENCHMARK_CONTEXT_CANONICAL="$bench_ctx"
else
  BENCHMARK_CONTEXT_CANONICAL=""
fi

# Resolve Codex executable
if [[ "$CODEX_EXECUTABLE" == */* ]]; then
  RESOLVED_EXECUTABLE="$(physical_path "$CODEX_EXECUTABLE")"
  [[ -x "$RESOLVED_EXECUTABLE" || -f "$RESOLVED_EXECUTABLE" ]] || die "Executable not found: $CODEX_EXECUTABLE"
else
  if ! command -v "$CODEX_EXECUTABLE" >/dev/null 2>&1; then
    die "Executable not found: $CODEX_EXECUTABLE"
  fi
  RESOLVED_EXECUTABLE="$(command -v "$CODEX_EXECUTABLE")"
fi

CLI_VERSION="unknown"
version_out="$("$RESOLVED_EXECUTABLE" --version 2>&1 || true)"
if [[ -n "$(echo "$version_out" | tr -d '[:space:]')" ]]; then
  CLI_VERSION="$(echo "$version_out" | awk 'NF{print; exit}')"
fi

if [[ "$SKIP_CODEX_VERSION_CHECK" -eq 0 ]]; then
  parsed_min="$(parse_semver "$MIN_CODEX_CLI_VERSION")"
  [[ -n "$parsed_min" ]] || die "Invalid MinCodexCliVersion '$MIN_CODEX_CLI_VERSION' (expected x.y.z)."
  parsed_cli="$(parse_semver "$CLI_VERSION")"
  if [[ -z "$parsed_cli" ]]; then
    die "Unable to parse Codex CLI version from '$CLI_VERSION'. Upgrade Codex or pass --SkipCodexVersionCheck only for emergency/test use. Minimum required: $MIN_CODEX_CLI_VERSION"
  fi
  if semver_lt "$parsed_cli" "$parsed_min"; then
    die "Codex CLI version $(echo "$parsed_cli" | tr ' ' '.') is below MinCodexCliVersion $MIN_CODEX_CLI_VERSION (raw: '$CLI_VERSION'). Upgrade with: npm install -g @openai/codex"
  fi
fi

case "$MODE" in
  ReviewReadOnly|ReviewWorkspace) SANDBOX_LEVEL="workspace-write" ;;
  FullAccess) SANDBOX_LEVEL="danger-full-access" ;;
esac
TEMP_WRITABLE_ROOT="{{RECEIPTS_DIR}}"

# --- run directory -----------------------------------------------------------

RUN_DIR="$(physical_path "$CANONICAL_OUTPUT_DIR/$DISPATCH_ID")"
path_under "$RUN_DIR" "$CANONICAL_OUTPUT_DIR" || die "Run directory must remain physically contained under OutputDir."

if [[ -e "$RUN_DIR" ]]; then
  if [[ "$FORCE" -eq 1 ]]; then
    RUN_DIR="$(physical_path "$RUN_DIR")"
    path_under "$RUN_DIR" "$CANONICAL_OUTPUT_DIR" || die "Run directory must remain physically contained under OutputDir before deletion."
    rm -rf "$RUN_DIR"
  else
    die "Collision error: Directory $RUN_DIR already exists. Use --Force to overwrite."
  fi
fi
mkdir -p "$RUN_DIR"

PROMPT_TEMP_FILE="$RUN_DIR/prompt_temp.txt"
if [[ -n "$PROMPT_TEXT" ]]; then
  printf '%s' "$PROMPT_TEXT" >"$PROMPT_TEMP_FILE"
else
  cp "$CANONICAL_PROMPT_FILE" "$PROMPT_TEMP_FILE"
fi

# Build argv
ARGS=()
if [[ "$USE_SEARCH" -eq 1 ]]; then
  ARGS+=(--search)
fi
ARGS+=(exec)
if [[ "$BENCHMARK_ISOLATION" -eq 1 ]]; then
  ARGS+=(--ephemeral --ignore-user-config --ignore-rules --strict-config)
fi
ARGS+=(-C "$CANONICAL_WORK_DIR")
ARGS+=(-m "$MODEL")
ARGS+=(-s "$SANDBOX_LEVEL")
ARGS+=(-c "model_reasoning_effort=$REASONING_EFFORT")
if [[ "$MODE" != "FullAccess" ]]; then
  ARGS+=(-c "sandbox_workspace_write.writable_roots=[\"$TEMP_WRITABLE_ROOT\"]")
fi

if [[ -n "$OUTPUT_SCHEMA" ]]; then
  FINAL_OUTPUT_FILE_NAME="final.json"
else
  FINAL_OUTPUT_FILE_NAME="final.md"
fi
FINAL_OUTPUT_PATH="$RUN_DIR/$FINAL_OUTPUT_FILE_NAME"

# Resolved once, for every Python helper this wrapper calls. Prefers the project venv so
# the helpers see the same dependencies the rest of the toolchain does, then PATH. Empty
# means there is no interpreter, which each caller below treats as fail-closed rather than
# assuming a bare `python3` exists.
PYTHON_EXE=""
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_EXE="$REPO_ROOT/.venv/bin/python"
else
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_EXE="$(command -v "$candidate")"
      break
    fi
  done
fi
SCHEMA_ADAPTER="$SCRIPT_DIR/adapt_output_schema.py"

API_SCHEMA_PATH="$CANONICAL_SCHEMA"
SCHEMA_ADAPT_NOTE=""
if [[ -n "$OUTPUT_SCHEMA" ]]; then
  # One shared implementation, called by both wrappers. This used to be four lines of
  # inline Python that popped `allOf` from the ROOT only, while the .ps1 twin recursed,
  # widened optionals and stripped the resulting nulls back out. Duplicated logic drifts:
  # on POSIX every schema-constrained review then died on a 400 naming a keyword nested
  # under `properties.findings.items`, a defect invisible on the machine where the other
  # copy was correct. See adapt_output_schema.py for what the adaptation is and why.
  stripped="$RUN_DIR/api-schema.json"
  if [[ ! -f "$SCHEMA_ADAPTER" ]]; then
    # Dispatch with the unmodified schema and say so. The endpoint will reject it with a
    # 400, which is loud and recoverable; what must not happen is a silent fallback that
    # makes the 400 look like the model's fault.
    SCHEMA_ADAPT_NOTE="schema adapter not found at $SCHEMA_ADAPTER, so the shipped schema was sent unadapted"
    echo "WARNING: $SCHEMA_ADAPT_NOTE" >&2
  elif [[ -z "$PYTHON_EXE" ]]; then
    SCHEMA_ADAPT_NOTE="no python3/python interpreter found, so the shipped schema was sent unadapted"
    echo "WARNING: $SCHEMA_ADAPT_NOTE" >&2
  elif adapt_output="$("$PYTHON_EXE" "$SCHEMA_ADAPTER" adapt "$CANONICAL_SCHEMA" "$stripped" 2>&1)"; then
    API_SCHEMA_PATH="$stripped"
  else
    SCHEMA_ADAPT_NOTE="schema adaptation failed: $(echo "$adapt_output" | tr -d '\r' | tr '\n' ' ')"
    echo "WARNING: $SCHEMA_ADAPT_NOTE" >&2
  fi
  ARGS+=(--output-schema "$API_SCHEMA_PATH")
  ARGS+=(-o "$FINAL_OUTPUT_PATH")
else
  ARGS+=(-o "$FINAL_OUTPUT_PATH")
fi
ARGS+=(--json)
ARGS+=(-)

# Persist sanitized argv (one arg per line for cmd_line clarity)
{
  printf '%q ' "$RESOLVED_EXECUTABLE"
  printf '%q ' "${ARGS[@]}"
  printf '< %q > %q 2> %q\n' "$PROMPT_TEMP_FILE" "$RUN_DIR/events.jsonl" "$RUN_DIR/stderr.txt"
} >"$RUN_DIR/cmd_line.txt"

START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH="$(date +%s)"

# $TIMEOUT_SEC was resolved next to the ledger gate (effort default, then the kind
# floor) so --GateOnly can report it and a review cannot reach this point holding a 0.

EVENTS_FILE="$RUN_DIR/events.jsonl"
: >"$EVENTS_FILE"
: >"$RUN_DIR/stderr.txt"

# Launch in a new process group when possible (Linux setsid; macOS falls back).
CHILD_PID=""
if command -v setsid >/dev/null 2>&1; then
  setsid "$RESOLVED_EXECUTABLE" "${ARGS[@]}" <"$PROMPT_TEMP_FILE" >"$EVENTS_FILE" 2>"$RUN_DIR/stderr.txt" &
  CHILD_PID=$!
else
  # macOS: start in background; tree cleanup uses pkill -P / PGID from ps.
  "$RESOLVED_EXECUTABLE" "${ARGS[@]}" <"$PROMPT_TEMP_FILE" >"$EVENTS_FILE" 2>"$RUN_DIR/stderr.txt" &
  CHILD_PID=$!
fi

ELAPSED_SEC=0
HAS_TERMINAL_EVENT=0
SAW_TERMINAL_BEFORE_TIMEOUT=0
KILLED=0
SALVAGED_AFTER_TIMEOUT=0

while (( ELAPSED_SEC < TIMEOUT_SEC )); do
  if ! kill -0 "$CHILD_PID" 2>/dev/null; then
    break
  fi
  sleep 1
  ELAPSED_SEC=$((ELAPSED_SEC + 1))

  if events_have_terminal "$EVENTS_FILE"; then
    HAS_TERMINAL_EVENT=1
    SAW_TERMINAL_BEFORE_TIMEOUT=1
    if [[ -f "$FINAL_OUTPUT_PATH" && -s "$FINAL_OUTPUT_PATH" ]]; then
      # ~5s natural-exit grace (10 × 0.5s), matching the PowerShell wrapper.
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$CHILD_PID" 2>/dev/null || break
        sleep 0.5
      done
      break
    fi
  fi
done

TIMED_OUT_WITHOUT_TERMINAL=0
if kill -0 "$CHILD_PID" 2>/dev/null && [[ "$SAW_TERMINAL_BEFORE_TIMEOUT" -eq 0 ]]; then
  TIMED_OUT_WITHOUT_TERMINAL=1
fi

if kill -0 "$CHILD_PID" 2>/dev/null; then
  KILLED=1
  stop_process_tree "$CHILD_PID"
fi

if [[ "$TIMED_OUT_WITHOUT_TERMINAL" -eq 1 && "$POST_KILL_GRACE_SEC" -gt 0 ]]; then
  grace_left="$POST_KILL_GRACE_SEC"
  while (( grace_left > 0 )); do
    if terminal_and_final_ready "$EVENTS_FILE" "$FINAL_OUTPUT_PATH"; then
      SALVAGED_AFTER_TIMEOUT=1
      break
    fi
    sleep 1
    grace_left=$((grace_left - 1))
  done
fi

END_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
END_EPOCH="$(date +%s)"
ELAPSED_MS=$(( (END_EPOCH - START_EPOCH) * 1000 ))

wait "$CHILD_PID" 2>/dev/null || true
CHILD_EXIT_CODE=$?
# If killed by signal, wait may return 128+N; keep as-is.

rm -f "$PROMPT_TEMP_FILE"

# Parse terminal events
TERMINAL_EVENT_COUNT=0
TERMINAL_EVENT_TYPE=""
ERROR_SUMMARY=""
HAS_MALFORMED_LINE=0
if [[ -f "$EVENTS_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "${line//[[:space:]]/}" ]] && continue
    parsed="$(python3 -c 'import json,sys
try:
  e=json.loads(sys.argv[1])
  t=e.get("type","")
  if t in ("turn.completed","turn.failed"):
    msg=""
    err=e.get("error") or {}
    if isinstance(err, dict):
      msg=err.get("message") or ""
    print(t+"\t"+msg)
except Exception:
  print("MALFORMED")
' "$line" 2>/dev/null || echo MALFORMED)"
    if [[ "$parsed" == "MALFORMED" ]]; then
      HAS_MALFORMED_LINE=1
      ERROR_SUMMARY="Malformed JSONL event line parsed."
      continue
    fi
    if [[ -n "$parsed" ]]; then
      TERMINAL_EVENT_TYPE="${parsed%%$'\t'*}"
      msg="${parsed#*$'\t'}"
      TERMINAL_EVENT_COUNT=$((TERMINAL_EVENT_COUNT + 1))
      if [[ "$TERMINAL_EVENT_TYPE" == "turn.failed" && -n "$msg" ]]; then
        ERROR_SUMMARY="$msg"
      fi
    fi
  done <"$EVENTS_FILE"
fi

SCHEMA_VALIDATION_ERROR=""
EXIT_VALUE="$CHILD_EXIT_CODE"

# Undo the nullable widening the API schema needed (see adapt_output_schema.py) BEFORE
# anything validates this file against the unmodified shipped schema, which is strict and
# would refuse `"mechanism": null` for a finding that legitimately has none. The pre-strip
# document is kept as final.raw.json rather than overwritten: a governance package must not
# rewrite a reviewer's output with no auditable copy of what it actually said.
NULL_STRIP_ERROR=""
if [[ -n "$OUTPUT_SCHEMA" && -f "$FINAL_OUTPUT_PATH" ]]; then
  if [[ ! -f "$SCHEMA_ADAPTER" ]]; then
    NULL_STRIP_ERROR="null-strip skipped: adapter not found at $SCHEMA_ADAPTER"
  elif [[ -z "$PYTHON_EXE" ]]; then
    NULL_STRIP_ERROR="null-strip skipped: no python3/python interpreter found"
  elif ! strip_output="$("$PYTHON_EXE" "$SCHEMA_ADAPTER" strip-nulls "$FINAL_OUTPUT_PATH" \
        --raw-copy "$RUN_DIR/final.raw.json" 2>&1)"; then
    # Not fatal on its own: the model's output is on disk either way, and the validation
    # below is what decides whether it is usable. Recorded so a downstream refusal is
    # traceable to this step rather than looking like the model's answer was malformed.
    NULL_STRIP_ERROR="$(echo "$strip_output" | tr -d '\r' | tr '\n' ' ')"
  fi
fi

if [[ -n "$OUTPUT_SCHEMA" && -f "$FINAL_OUTPUT_PATH" ]]; then
  VALIDATOR="$SCRIPT_DIR/validate_json_schema.py"
  if [[ -z "$PYTHON_EXE" ]]; then
    SCHEMA_VALIDATION_ERROR="no python3/python interpreter found, so $FINAL_OUTPUT_FILE_NAME was NOT validated. This is the absence of a check, not a failed one."
    EXIT_VALUE=3
    ERROR_SUMMARY="FAIL-CLOSED: $SCHEMA_VALIDATION_ERROR"
  elif [[ ! -f "$VALIDATOR" ]]; then
    # 3, not 0. This branch used to be an empty `if` with no `else`: an absent validator
    # meant the verdict was never checked and the wrapper reported success anyway, which
    # is how an unrun check comes to be believed. "Never checked" is also not 1 -- calling
    # it a validation failure blames a clean output for a missing file.
    SCHEMA_VALIDATION_ERROR="validator not found at $VALIDATOR, so $FINAL_OUTPUT_FILE_NAME was NOT validated. This is the absence of a check, not a failed one."
    EXIT_VALUE=3
    ERROR_SUMMARY="FAIL-CLOSED: $SCHEMA_VALIDATION_ERROR"
  else
    validation_output="$("$PYTHON_EXE" "$VALIDATOR" "$FINAL_OUTPUT_PATH" "$CANONICAL_SCHEMA" 2>&1)"
    validation_code=$?
    if [[ "$validation_code" -ne 0 ]]; then
      SCHEMA_VALIDATION_ERROR="$(echo "$validation_output" | tr -d '\r')"
      # Propagate the validator's own 3 rather than flattening it to 1: 3 means jsonschema
      # is not installed, which is an environment problem to fix, not a verdict to reject.
      if [[ "$validation_code" -eq 3 ]]; then
        EXIT_VALUE=3
        ERROR_SUMMARY="JSON Schema validation could not run: $SCHEMA_VALIDATION_ERROR"
      else
        EXIT_VALUE=1
        ERROR_SUMMARY="JSON Schema validation failed: $SCHEMA_VALIDATION_ERROR"
      fi
    fi
  fi
fi

LATE_COMPLETION_OK=0
if [[ "$SALVAGED_AFTER_TIMEOUT" -eq 1 \
   && "$TERMINAL_EVENT_COUNT" -eq 1 \
   && "$TERMINAL_EVENT_TYPE" == "turn.completed" \
   && "$HAS_MALFORMED_LINE" -eq 0 \
   && -z "$SCHEMA_VALIDATION_ERROR" \
   && -f "$FINAL_OUTPUT_PATH" && -s "$FINAL_OUTPUT_PATH" ]]; then
  LATE_COMPLETION_OK=1
fi

IS_SUCCESS=0
if { [[ "$KILLED" -eq 0 && "$EXIT_VALUE" -eq 0 ]] || [[ "$LATE_COMPLETION_OK" -eq 1 ]]; } \
   && [[ "$TERMINAL_EVENT_COUNT" -eq 1 \
      && "$TERMINAL_EVENT_TYPE" == "turn.completed" \
      && "$HAS_MALFORMED_LINE" -eq 0 \
      && -z "$SCHEMA_VALIDATION_ERROR" ]]; then
  IS_SUCCESS=1
fi

if [[ "$IS_SUCCESS" -eq 1 ]]; then
  WRAPPER_EXIT_CODE=0
else
  if [[ "$EXIT_VALUE" -ne 0 ]]; then
    WRAPPER_EXIT_CODE="$EXIT_VALUE"
  else
    WRAPPER_EXIT_CODE=3
  fi
fi

if [[ "$IS_SUCCESS" -eq 1 && "$LATE_COMPLETION_OK" -eq 1 ]]; then
  ERROR_SUMMARY=""
elif [[ "$IS_SUCCESS" -eq 0 && -z "$ERROR_SUMMARY" ]]; then
  ERROR_SUMMARY="Terminal event validation failed (Count: $TERMINAL_EVENT_COUNT, Type: $TERMINAL_EVENT_TYPE)"
fi

if [[ "$IS_SUCCESS" -eq 1 ]]; then
  if [[ "$RETENTION" == "CompressOnSuccess" && -f "$EVENTS_FILE" ]]; then
    gzip -f -c "$EVENTS_FILE" >"$EVENTS_FILE.gz"
    rm -f "$EVENTS_FILE"
  elif [[ "$RETENTION" == "DeleteOnSuccess" ]]; then
    rm -f "$EVENTS_FILE" "$RUN_DIR/stderr.txt"
  fi
fi

# Artifact sizes + status.json via python for stable JSON (env-based, no shell quoting traps)
WRAPPER_SHA="$(sha256_file "$SCRIPT_PATH")"
OUTPUT_SCHEMA_SHA=""
if [[ -n "$CANONICAL_SCHEMA" && -f "$CANONICAL_SCHEMA" ]]; then
  OUTPUT_SCHEMA_SHA="$(sha256_file "$CANONICAL_SCHEMA")"
fi
WORKING_AGENTS_SHA=""
if [[ -f "$CANONICAL_WORK_DIR/AGENTS.md" ]]; then
  WORKING_AGENTS_SHA="$(sha256_file "$CANONICAL_WORK_DIR/AGENTS.md")"
fi

EFFECTIVE_CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
EFFECTIVE_CODEX_HOME="$(physical_path "$EFFECTIVE_CODEX_HOME")"

PROCESS_TREE_KILL=1
[[ "$NO_PROCESS_TREE_KILL" -eq 1 ]] && PROCESS_TREE_KILL=0

SANITIZED_ARGV_JSON="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' -- "${ARGS[@]}")"

export ICD_STATUS_PATH="$RUN_DIR/status.json"
export ICD_FINAL_PATH="$FINAL_OUTPUT_PATH"
export ICD_EVENTS_PATH="$EVENTS_FILE"
export ICD_STDERR_PATH="$RUN_DIR/stderr.txt"
export ICD_FINAL_NAME="$FINAL_OUTPUT_FILE_NAME"
export ICD_SANITIZED_ARGV_JSON="$SANITIZED_ARGV_JSON"
export ICD_DISPATCH_ID="$DISPATCH_ID"
export ICD_MODEL="$MODEL"
export ICD_LOOP_ID="$LOOP_ID"
export ICD_LEDGER_GATE="$LEDGER_GATE_RESULT"
export ICD_DISPATCH_KIND="$DISPATCH_KIND"
export ICD_TIMEOUT_FLOOR_APPLIED="$TIMEOUT_FLOOR_APPLIED"
export ICD_MODE="$MODE"
export ICD_SANDBOX="$SANDBOX_LEVEL"
export ICD_EFFORT="$REASONING_EFFORT"
export ICD_RETENTION="$RETENTION"
export ICD_START_UTC="$START_UTC"
export ICD_END_UTC="$END_UTC"
export ICD_ELAPSED_MS="$ELAPSED_MS"
export ICD_TIMEOUT_SEC="$TIMEOUT_SEC"
export ICD_POST_KILL_GRACE_SEC="$POST_KILL_GRACE_SEC"
export ICD_PROCESS_TREE_KILL="$PROCESS_TREE_KILL"
export ICD_SALVAGED="$SALVAGED_AFTER_TIMEOUT"
export ICD_CLI_VERSION="$CLI_VERSION"
export ICD_WRAPPER_EXIT="$WRAPPER_EXIT_CODE"
export ICD_CHILD_EXIT="$CHILD_EXIT_CODE"
export ICD_TERM_COUNT="$TERMINAL_EVENT_COUNT"
export ICD_TERM_TYPE="$TERMINAL_EVENT_TYPE"
export ICD_ERROR_SUMMARY="$ERROR_SUMMARY"
export ICD_NULL_STRIP_ERROR="$NULL_STRIP_ERROR"
export ICD_SCHEMA_ADAPT_NOTE="$SCHEMA_ADAPT_NOTE"
if [[ -f "$RUN_DIR/final.raw.json" ]]; then
  export ICD_NULL_STRIP_RAW_KEPT=1
else
  export ICD_NULL_STRIP_RAW_KEPT=0
fi
export ICD_BENCH="$BENCHMARK_ISOLATION"
export ICD_BENCH_RECEIPT="$BENCHMARK_CONTEXT_CANONICAL"
export ICD_BENCH_SHA="$BENCHMARK_CONTEXT_SHA256"
export ICD_WRAPPER_SHA="$WRAPPER_SHA"
export ICD_SCHEMA_SHA="$OUTPUT_SCHEMA_SHA"
export ICD_AGENTS_SHA="$WORKING_AGENTS_SHA"
export ICD_WORK_DIR="$CANONICAL_WORK_DIR"
export ICD_CODEX_HOME="$EFFECTIVE_CODEX_HOME"
export ICD_FA_JUST="$FULL_ACCESS_JUSTIFICATION"

python3 <<'PY'
import json, os

def env(name, default=""):
    return os.environ.get(name, default)

out = env("ICD_STATUS_PATH")
final = env("ICD_FINAL_PATH")
events = env("ICD_EVENTS_PATH")
stderr = env("ICD_STDERR_PATH")
name = env("ICD_FINAL_NAME")
sizes = {}
if os.path.isfile(final):
    sizes[name] = os.path.getsize(final)
if os.path.isfile(events + ".gz"):
    sizes["events.jsonl.gz"] = os.path.getsize(events + ".gz")
if os.path.isfile(events):
    sizes["events.jsonl"] = os.path.getsize(events)
if os.path.isfile(stderr):
    sizes["stderr.txt"] = os.path.getsize(stderr)

child_raw = env("ICD_CHILD_EXIT")
try:
    child_exit = int(child_raw)
except ValueError:
    child_exit = None

manifest = {
    "schema_version": "dispatch-status.v1",
    "dispatch_id": env("ICD_DISPATCH_ID"),
    "model": env("ICD_MODEL"),
    # The review-loop bound, recorded so a bypass leaves a trace.
    # `bypassed-non-review` in a receipt whose prompt was plainly a review is the
    # audit signal.
    "loop_id": env("ICD_LOOP_ID") or None,
    "ledger_gate": env("ICD_LEDGER_GATE"),
    # The kind the ledger recorded for this loop, not the flag the caller typed, plus
    # whether it moved the timeout. A truncated execution review whose receipt says
    # `timeout_floor_applied: false` is a wrapper/ledger pairing problem; one that says
    # true is a genuinely long review.
    "dispatch_kind": env("ICD_DISPATCH_KIND"),
    "timeout_floor_applied": bool(int(env("ICD_TIMEOUT_FLOOR_APPLIED") or "0")),
    "mode": env("ICD_MODE"),
    "sandbox": env("ICD_SANDBOX"),
    "reasoning_effort": env("ICD_EFFORT"),
    "retention": env("ICD_RETENTION"),
    "output_paths": {"final_output": final},
    "sanitized_argv": json.loads(env("ICD_SANITIZED_ARGV_JSON") or "[]"),
    "start_utc": env("ICD_START_UTC"),
    "end_utc": env("ICD_END_UTC"),
    "elapsed_ms": int(env("ICD_ELAPSED_MS") or "0"),
    "timeout_sec": int(env("ICD_TIMEOUT_SEC") or "0"),
    "post_kill_grace_sec": int(env("ICD_POST_KILL_GRACE_SEC") or "0"),
    "process_tree_kill": bool(int(env("ICD_PROCESS_TREE_KILL") or "0")),
    "salvaged_after_timeout": bool(int(env("ICD_SALVAGED") or "0")),
    "cli_version": env("ICD_CLI_VERSION"),
    "exit_code": int(env("ICD_WRAPPER_EXIT") or "0"),
    "child_exit_code": child_exit,
    "artifact_sizes": sizes,
    "terminal_event_count": int(env("ICD_TERM_COUNT") or "0"),
    "terminal_event_type": env("ICD_TERM_TYPE"),
    "error_summary": env("ICD_ERROR_SUMMARY"),
    # Null-strip and schema-adaptation outcomes. Recorded even on success (as None) so
    # their absence from an old status.json is distinguishable from "it ran and had
    # nothing to say". These are the same keys the .ps1 twin writes; the two wrappers
    # feed the same downstream readers, so their status artifacts must agree.
    "null_strip_error": env("ICD_NULL_STRIP_ERROR") or None,
    "null_strip_raw_kept": bool(int(env("ICD_NULL_STRIP_RAW_KEPT") or "0")),
    "schema_adapt_error": env("ICD_SCHEMA_ADAPT_NOTE") or None,
    "benchmark_isolation": bool(int(env("ICD_BENCH") or "0")),
    "benchmark_context_receipt": env("ICD_BENCH_RECEIPT") or None,
    "benchmark_context_sha256": env("ICD_BENCH_SHA") or None,
    "wrapper_sha256": env("ICD_WRAPPER_SHA"),
    "output_schema_sha256": env("ICD_SCHEMA_SHA") or None,
    "working_directory_agents_sha256": env("ICD_AGENTS_SHA") or None,
    "working_directory": env("ICD_WORK_DIR"),
    "sanitized_environment": {
        "effective_codex_home": env("ICD_CODEX_HOME"),
        "allowlisted_keys": ["CODEX_HOME", "HOME", "PATH", "USERPROFILE"],
    },
}
if env("ICD_MODE") == "FullAccess":
    n = len(env("ICD_FA_JUST"))
    bucket = "20-79" if n <= 79 else ("80-199" if n <= 199 else "200-plus")
    manifest["full_access_justification_supplied"] = True
    manifest["full_access_justification_redacted"] = "[REDACTED]"
    manifest["full_access_justification_length_bucket"] = bucket

tmp = out + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
os.replace(tmp, out)
PY

cat >"$RUN_DIR/receipt.txt" <<EOF
Dispatch ID: $DISPATCH_ID
Model: $MODEL
Mode: $MODE
Sandbox: $SANDBOX_LEVEL
Exit Code: $WRAPPER_EXIT_CODE
Child Exit Code: $CHILD_EXIT_CODE
Start: $START_UTC
End: $END_UTC
Elapsed: $ELAPSED_MS ms
CLI Version: $CLI_VERSION
EOF

exit "$WRAPPER_EXIT_CODE"
