#!/usr/bin/env bash
# Invoke-CodexDispatch.sh — POSIX/macOS companion to Invoke-CodexDispatch.ps1
#
# Same dispatch contract: mode/sandbox mapping, version gate, path containment,
# timeout + process-tree cleanup, receipt/status artifacts, optional schema check.
# Prefer this on macOS/Linux when pwsh is unavailable; otherwise either wrapper is valid.
#
# Placeholders (filled by scripts/instantiate.py):
#   {{RECEIPTS_DIR}}  {{PROJECT_ROOT}}
#
set -u
set -o pipefail

SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

MODE="ReviewReadOnly"
REASONING_EFFORT="high"
RETENTION="CompressOnSuccess"
MODEL="gpt-5.6-sol"
PROMPT_FILE=""
PROMPT_TEXT=""
DISPATCH_ID=""
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

Common:
  --Mode ReviewReadOnly|ReviewWorkspace|FullAccess
  --ReasoningEffort medium|high|xhigh|max
  --Retention Keep|CompressOnSuccess|DeleteOnSuccess
  --Model NAME
  --DispatchId ID
  --OutputDir PATH          (must stay under {{RECEIPTS_DIR}})
  --OutputSchema PATH
  --WorkingDirectory PATH   (must stay under {{PROJECT_ROOT}})
  --CodexExecutable PATH|NAME
  --FullAccessJustification TEXT   (required for FullAccess; ≥20 non-ws chars)
  --ApiKeyEnvVar NAME
  --TimeoutSec N            (0 = derive from ReasoningEffort)
  --PostKillGraceSec N
  --MinCodexCliVersion x.y.z
  --UseSearch
  --Force
  --NoProcessTreeKill
  --SkipCodexVersionCheck
  --BenchmarkIsolation
  --BenchmarkContextReceipt PATH
  --BenchmarkContextSha256 HEX64
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --Mode) MODE="${2:-}"; shift 2 ;;
    --ReasoningEffort) REASONING_EFFORT="${2:-}"; shift 2 ;;
    --Retention) RETENTION="${2:-}"; shift 2 ;;
    --Model) MODEL="${2:-}"; shift 2 ;;
    --PromptFile) PROMPT_FILE="${2:-}"; shift 2 ;;
    --PromptText) PROMPT_TEXT="${2:-}"; shift 2 ;;
    --DispatchId) DISPATCH_ID="${2:-}"; shift 2 ;;
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
if [[ -z "$MODEL" ]]; then
  die "Model must be specified."
fi
if [[ ! "$MODEL" =~ ^[a-zA-Z0-9.-]+$ ]]; then
  die "Invalid Model format."
fi

RECEIPTS_ROOT="$(physical_path "{{RECEIPTS_DIR}}")"
REPO_ROOT="$(physical_path "{{PROJECT_ROOT}}")"

if [[ "$BENCHMARK_ISOLATION" -eq 1 ]]; then
  [[ "$MODE" == "ReviewReadOnly" ]] || die "BenchmarkIsolation requires Mode ReviewReadOnly."
  [[ "$REASONING_EFFORT" == "medium" ]] || die "BenchmarkIsolation requires ReasoningEffort medium."
  [[ "$MODEL" == "gpt-5.6-sol" ]] || die "BenchmarkIsolation requires Model gpt-5.6-sol."
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

API_SCHEMA_PATH="$CANONICAL_SCHEMA"
if [[ -n "$OUTPUT_SCHEMA" ]]; then
  stripped="$RUN_DIR/api-schema.json"
  if python3 - "$CANONICAL_SCHEMA" "$stripped" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    data = json.load(f)
data.pop("allOf", None)
with open(dst, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  then
    API_SCHEMA_PATH="$stripped"
  else
    API_SCHEMA_PATH="$CANONICAL_SCHEMA"
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

if [[ "$TIMEOUT_SEC" -le 0 ]]; then
  TIMEOUT_SEC="$(default_timeout "$REASONING_EFFORT")"
fi

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
if [[ -n "$OUTPUT_SCHEMA" && -f "$FINAL_OUTPUT_PATH" ]]; then
  PYTHON_EXE="python3"
  if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
    PYTHON_EXE="$REPO_ROOT/.venv/bin/python"
  fi
  VALIDATOR="$REPO_ROOT/tools/validate_json_schema.py"
  if [[ -f "$VALIDATOR" ]]; then
    if ! validation_output="$("$PYTHON_EXE" "$VALIDATOR" "$FINAL_OUTPUT_PATH" "$CANONICAL_SCHEMA" 2>&1)"; then
      SCHEMA_VALIDATION_ERROR="$(echo "$validation_output" | tr -d '\r')"
      EXIT_VALUE=1
      ERROR_SUMMARY="JSON Schema validation failed: $SCHEMA_VALIDATION_ERROR"
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
