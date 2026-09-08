#!/usr/bin/env bash
#
# tools/preflight.sh -- environment prerequisites as a runnable check.
#
# Every fact this script proves used to be a caveat in an always-loaded doc: "assume rg
# may be a shell function", "receipts live outside the repo", "assume pwsh is not
# installed on macOS". Those lines cost context in every session and were still only
# claims. A command that exits non-zero costs nothing until it fails, and it fails on the
# machine where the assumption is wrong instead of three steps later inside a review.
#
# Usage:
#   tools/preflight.sh                     # every check
#   tools/preflight.sh --phase build       # skip the dispatch checks (no review this session)
#   tools/preflight.sh --only rg           # one check, by name
#   tools/preflight.sh --selftest          # prove each check can fail, and can pass
#
# Exit codes (the package-wide discipline: 3 is never 1):
#   0  every check that ran passed (warnings do not fail the run)
#   1  a prerequisite is missing -- fix it before dispatching or building
#   2  usage error
#   3  the check itself could not run (no writable temp, no mktemp)
#
# First stdout line is always OK:/REFUSE:/FAIL-CLOSED:/USAGE: so a caller can `grep -qx`.
#
# bash 3.2 compatible on purpose: that is what /bin/bash is on macOS, and this is the one
# script an adopter runs *before* discovering their bash is old.

set -u

# The defaults are instantiate tokens. An uninstantiated token is itself a finding -- see
# chk_receipts -- so the script is useful before instantiate.py has run, and says why.
DEFAULT_RECEIPTS_DIR="{{RECEIPTS_DIR}}"
MIN_CODEX_CLI_VERSION="0.145.0"
MIN_PYTHON_MINOR=9        # 3.9: the package's tools annotate `tuple[list[str], ...]`

PHASE="all"
ONLY=""
SELFTEST=0

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
SKIP_COUNT=0
FAIL_NAMES=""

usage() {
  cat <<'EOF'
USAGE: tools/preflight.sh [--phase all|build|review] [--only NAME] [--selftest]

Checks (NAME for --only):
  receipts   RECEIPTS_DIR is set, absolute, outside the repo, and writable
  rg         rg is a binary on PATH and was proven able to match
  python     python3/python >= 3.9 with pyyaml + jsonschema importable
  registry   the model registry home resolves through the documented S2 order
  git        git is on PATH and the working tree is readable
  codex      codex CLI present and >= 0.145.0            (phase: all, review)
  pwsh       PowerShell availability for the .ps1 twins   (phase: all, review)
  sync       repo / receipts are not inside a cloud-sync working copy

Exit: 0 pass, 1 a prerequisite is missing, 2 usage, 3 the check could not run.
EOF
}

# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------

report() {
  # report NAME STATUS DETAIL
  printf '  %-9s %-5s %s\n' "$1" "$2" "$3"
  case "$2" in
    PASS) PASS_COUNT=$((PASS_COUNT + 1)) ;;
    FAIL) FAIL_COUNT=$((FAIL_COUNT + 1)); FAIL_NAMES="$FAIL_NAMES $1" ;;
    WARN) WARN_COUNT=$((WARN_COUNT + 1)) ;;
    SKIP) SKIP_COUNT=$((SKIP_COUNT + 1)) ;;
  esac
}

fail_closed() {
  printf 'FAIL-CLOSED: %s\n' "$1" >&2
  exit 3
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

repo_root() {
  # git first, because it is the only source that is right when the script is invoked
  # through a symlink or from a subdirectory. The token fallback covers a tree that has
  # been instantiated but not yet committed; the path fallback covers neither.
  local root
  if command -v git >/dev/null 2>&1; then
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [[ -n "$root" ]]; then printf '%s\n' "$root"; return 0; fi
  fi
  root="{{PROJECT_ROOT}}"
  case "$root" in
    *'{{'*) root="$(cd "$(dirname "$0")/.." && pwd)" ;;
  esac
  printf '%s\n' "$root"
}

path_under() {
  # path_under CHILD PARENT -> 0 if CHILD == PARENT or CHILD is inside PARENT
  [[ "$1" == "$2" || "$1" == "$2"/* ]]
}

# --- propagate, don't infer ------------------------------------------------
#
# Three defects in this package shared one mechanism, so it is written down once here
# rather than patched three times: **a status was inferred from a command's text, or
# from the presence of a value, instead of taken from the process that produced it.**
#
# The two shapes it takes in shell:
#
#   out="$(cmd 2>&1 || true)"      merges stderr into stdout and throws the status
#                                  away, leaving a `case` on the text as the only
#                                  evidence -- so a command that FAILS while printing
#                                  the expected string reads as success.
#   dir="$(make_temp_dir)"         runs the callee in a subshell, so a `fail_closed`
#                                  inside it exits only that subshell; the parent
#                                  continues with an empty path and reports OK.
#
# The rule: a probe's stdout, stderr and exit status are three separate facts, and the
# status is the one that decides. Anything run inside `$(...)` must have its status
# consulted at the call site, because the callee cannot terminate the parent from there.

make_temp_dir() {
  # BSD mktemp only expands *trailing* Xs. `mktemp -d dir/pf-XXXXXX.d` is a constant
  # name on macOS: the first call succeeds and every later one collides, which reads as
  # a flaky check rather than a broken one.
  #
  # Returns 3 instead of calling fail_closed, because every caller invokes this inside
  # `$(...)`: an `exit 3` there terminated the subshell and left the parent running with
  # dir="" -- preflight printed FAIL-CLOSED and still exited 0. Callers must therefore
  # be `dir="$(make_temp_dir)" || fail_closed ...`; the status of that assignment IS the
  # substitution's status, which is what makes the propagation work.
  command -v mktemp >/dev/null 2>&1 || {
    printf 'no mktemp on PATH, so the checks that need a scratch directory cannot run.\n' >&2
    return 3
  }
  mktemp -d "${TMPDIR:-/tmp}/preflight-XXXXXX" 2>/dev/null || {
    printf 'mktemp could not create a scratch directory under %s.\n' "${TMPDIR:-/tmp}" >&2
    return 3
  }
}

semver_lt() {
  # semver_lt A B -> 0 if A < B, comparing x.y.z numerically
  local a1 a2 a3 b1 b2 b3
  IFS=. read -r a1 a2 a3 <<EOF
$1
EOF
  IFS=. read -r b1 b2 b3 <<EOF
$2
EOF
  [[ -n "${a1:-}" && -n "${b1:-}" ]] || return 1
  a2="${a2:-0}"; a3="${a3:-0}"; b2="${b2:-0}"; b3="${b3:-0}"
  if (( a1 != b1 )); then (( a1 < b1 )); return $?; fi
  if (( a2 != b2 )); then (( a2 < b2 )); return $?; fi
  (( a3 < b3 ))
}

# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------

chk_receipts() {
  local dir="${RECEIPTS_DIR:-$DEFAULT_RECEIPTS_DIR}" root probe
  case "$dir" in
    *'{{'*)
      report receipts FAIL "receipts dir is an uninstantiated token ('$dir'). Set RECEIPTS_DIR, or run .agent/INSTANTIATE.md's substitution step. Creating this path would make a literal '{{...}}' directory that the next tool will not look in."
      return 1 ;;
  esac
  if [[ -z "$dir" ]]; then
    report receipts FAIL "RECEIPTS_DIR is empty. There is deliberately no default: an unset variable must fail closed rather than write receipts where the next invocation will not look."
    return 1
  fi
  case "$dir" in
    /*|[A-Za-z]:[/\\]*) ;;
    *) report receipts FAIL "receipts dir '$dir' is relative. It is resolved by several tools with different working directories, so a relative path means different directories per caller."
       return 1 ;;
  esac
  root="$(repo_root)"
  if path_under "$dir" "$root"; then
    report receipts FAIL "receipts dir '$dir' is inside the repo ($root). Receipts are raw tool output: they carry model slugs and absolute paths, and inside the repo they end up in a commit or trip the release slug gate (ADOPTION-QUESTIONS A4b/F3)."
    return 1
  fi
  mkdir -p "$dir" 2>/dev/null || {
    report receipts FAIL "receipts dir '$dir' could not be created."
    return 1
  }
  probe="$dir/.preflight-probe.$$"
  if ! ( : >"$probe" ) 2>/dev/null; then
    report receipts FAIL "receipts dir '$dir' exists but is not writable. Every P0 redirect in this package writes there."
    return 1
  fi
  rm -f "$probe"
  report receipts PASS "$dir (absolute, outside $root, writable)"
  return 0
}

chk_rg() {
  local kind fixture dir out err status
  if ! command -v rg >/dev/null 2>&1; then
    report rg FAIL "rg is not on PATH. Several sweeps in this package are 'zero matches means clean'; with rg absent they exit 127, which reads as zero matches."
    return 1
  fi
  # `type -t` distinguishes a binary from a function/alias. An interactive shell that
  # defines `rg` as a function gives a non-interactive subshell nothing: the command
  # exits 127, and a sweep whose contract is "no output means clean" calls that clean.
  kind="$(type -t rg 2>/dev/null || echo unknown)"
  if [[ "$kind" != "file" ]]; then
    report rg FAIL "rg resolves to a shell $kind, not a binary on PATH. Non-interactive subshells -- which is how every tool here calls it -- will get 127."
    return 1
  fi
  # Proven able to match, not merely present (V5): zero matches is evidence only from a
  # detector that was just shown to produce one.
  dir="$(make_temp_dir)" || fail_closed "no scratch directory for the rg fixture, so rg was never proven able to match. Exit 3: nothing was checked."
  fixture="$dir/fixture.txt"
  printf 'PREFLIGHT-CANARY-STRING\n' >"$fixture"
  # stdout, stderr and status kept apart -- see "propagate, don't infer" above. The old
  # `out="$(rg ... 2>&1 || true)"` reported PASS for a stub that exited 2 after writing
  # the canary to *stderr*: the check was reading its own expected string back out of an
  # error message. Both halves now have to hold.
  rg -n 'PREFLIGHT-CANARY-STRING' "$fixture" >"$dir/rg.out" 2>"$dir/rg.err"; status=$?
  out="$(cat "$dir/rg.out" 2>/dev/null || true)"
  err="$(cat "$dir/rg.err" 2>/dev/null || true)"
  rm -rf "$dir" 2>/dev/null || true
  # rg's own statuses: 0 matched, 1 no match, 2 error. They are different findings and the
  # message has to say which, because "did not match" sends you to look at your pattern and
  # "errored" sends you to look at your install.
  if (( status == 1 )); then
    report rg FAIL "rg did not match a fixture containing the string it was given (exit 1 = no match; stderr: ${err:-<empty>}). A detector that cannot match cannot report a clean sweep."
    return 1
  fi
  if (( status != 0 )); then
    report rg FAIL "rg exited $status (an error, not a no-match) on a fixture that contains the string it was handed (stderr: ${err:-<empty>}). Every 'no output means clean' sweep in this package would read that as clean."
    return 1
  fi
  case "$out" in
    *PREFLIGHT-CANARY-STRING*)
      report rg PASS "$(command -v rg) matched a known fixture"
      return 0 ;;
  esac
  report rg FAIL "rg exited 0 but printed no match on stdout for a fixture containing the string it was given (stdout: ${out:-<empty>}, stderr: ${err:-<empty>}). A detector that cannot match cannot report a clean sweep."
  return 1
}

chk_python() {
  local py="" candidate ver minor missing=""
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then py="$candidate"; break; fi
  done
  if [[ -z "$py" ]]; then
    report python FAIL "neither python3 nor python is on PATH. review_ledger.py, the closeout gates, and the wrappers' ledger call all need it -- the wrappers exit 3 without it, which is 'could not check', not a pass."
    return 1
  fi
  ver="$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || true)"
  if [[ -z "$ver" ]]; then
    report python FAIL "'$py' is on PATH but did not report a version."
    return 1
  fi
  minor="${ver#*.}"
  if [[ "${ver%%.*}" != "3" ]] || (( minor < MIN_PYTHON_MINOR )); then
    report python FAIL "python $ver is below the 3.$MIN_PYTHON_MINOR this package's tools are written against (they annotate builtin generics)."
    return 1
  fi
  for candidate in yaml jsonschema; do
    "$py" -c "import $candidate" >/dev/null 2>&1 || missing="$missing $candidate"
  done
  if [[ -n "$missing" ]]; then
    report python FAIL "python $ver but missing:$missing (pip install pyyaml jsonschema). Without jsonschema the verdict schema check exits 3 and no round can be recorded."
    return 1
  fi
  report python PASS "$py $ver with pyyaml + jsonschema"
  return 0
}

chk_registry() {
  # The documented S2 order, in order. A baked drive letter is one machine's layout: dead
  # on macOS/Linux, and on another Windows box with that letter it silently reads someone
  # else's registry.
  local home="" rung="" candidate
  # The two rungs are different *kinds* of path, and .agent/INSTANTIATE.md S2 is the
  # authority: AGENT_MODEL_REGISTRY names the compiled JSON **file** ("must name the
  # file, not the directory holding it"), AGENT_MODEL_REGISTRY_HOME names a directory
  # containing it. Treating the first as a directory made a correct file override fail
  # with "registry home does not exist" -- a true-sounding message pointing at the wrong
  # thing, which costs more than no check at all.
  if [[ -n "${AGENT_MODEL_REGISTRY:-}" ]]; then
    if [[ -d "$AGENT_MODEL_REGISTRY" ]]; then
      report registry FAIL "AGENT_MODEL_REGISTRY ('$AGENT_MODEL_REGISTRY') is a directory, but that rung names the compiled JSON file (.agent/INSTANTIATE.md S2). Use AGENT_MODEL_REGISTRY_HOME for a directory."
      return 1
    fi
    if [[ ! -f "$AGENT_MODEL_REGISTRY" ]]; then
      report registry FAIL "AGENT_MODEL_REGISTRY ('$AGENT_MODEL_REGISTRY') does not name an existing file. -ModelClass resolution reads that file; without it a dispatch cannot bind a class to a snapshot."
      return 1
    fi
    case "$AGENT_MODEL_REGISTRY" in
      *.json) ;;
      *) report registry FAIL "AGENT_MODEL_REGISTRY ('$AGENT_MODEL_REGISTRY') is not a .json file. The resolver consumes the *compiled* registry; the .yaml source is what you edit and is not interchangeable with it."
         return 1 ;;
    esac
    report registry PASS "$AGENT_MODEL_REGISTRY (via AGENT_MODEL_REGISTRY)"
    return 0
  fi
  if [[ -n "${AGENT_MODEL_REGISTRY_HOME:-}" ]]; then
    home="$AGENT_MODEL_REGISTRY_HOME"; rung="AGENT_MODEL_REGISTRY_HOME"
  elif [[ -n "${USERPROFILE:-}" ]]; then
    home="$USERPROFILE/.agent"; rung='$USERPROFILE/.agent'
  elif [[ -n "${HOME:-}" ]]; then
    home="$HOME/.agent"; rung='$HOME/.agent'
  fi
  if [[ -z "$home" ]]; then
    report registry FAIL "no registry home: AGENT_MODEL_REGISTRY and AGENT_MODEL_REGISTRY_HOME are unset and neither USERPROFILE nor HOME is set. See .agent/INSTANTIATE.md."
    return 1
  fi
  if [[ ! -d "$home" ]]; then
    report registry FAIL "registry home '$home' (from $rung) does not exist. -ModelClass resolution reads the live registry there; without it a dispatch cannot bind a class to a snapshot."
    return 1
  fi
  if [[ -f "$home/model-registry.json" ]]; then
    report registry PASS "$home/model-registry.json (via $rung)"
    return 0
  fi
  # A YAML source with no compiled JSON is its own state, and saying so is the whole
  # value of the check: accepting the .yaml here passed a machine that then could not
  # resolve a single class, because the resolver only ever reads the compiled JSON.
  for candidate in "$home/model-registry.yaml" "$home/model-registry.yml"; do
    if [[ -f "$candidate" ]]; then
      report registry FAIL "registry home '$home' (from $rung) has $candidate but no compiled model-registry.json. The YAML is the source you edit; the resolver reads the compiled JSON. Compile it before dispatching."
      return 1
    fi
  done
  report registry FAIL "registry home '$home' (from $rung) has no model-registry.json. The directory existing is not the registry existing."
  return 1
}

chk_git() {
  local root
  if ! command -v git >/dev/null 2>&1; then
    report git FAIL "git is not on PATH. The review sweeps read 'git diff' / 'git status' for claim verification."
    return 1
  fi
  root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
  if [[ -z "$root" ]]; then
    report git FAIL "git is present but this is not a work tree (git rev-parse --show-toplevel failed)."
    return 1
  fi
  report git PASS "$root"
  return 0
}

chk_codex() {
  local raw ver
  if [[ "$PHASE" == "build" ]]; then
    report codex SKIP "phase=build; no independent-review dispatch this session"
    return 0
  fi
  if ! command -v codex >/dev/null 2>&1; then
    report codex FAIL "codex is not on PATH, so no independent review can be dispatched. Self-review is prohibited, so the sanctioned move is to escalate to a human -- not to review your own work. Install: npm install -g @openai/codex."
    return 1
  fi
  raw="$(codex --version 2>&1 | head -n 1 || true)"
  ver="$(printf '%s\n' "$raw" | sed -n 's/.*\([0-9]\{1,\}\.[0-9]\{1,\}\.[0-9]\{1,\}\).*/\1/p' | head -n 1)"
  if [[ -z "$ver" ]]; then
    report codex FAIL "codex is on PATH but its version is unparseable ('$raw'). The wrapper fails closed on this too, so it would refuse the dispatch."
    return 1
  fi
  if semver_lt "$ver" "$MIN_CODEX_CLI_VERSION"; then
    report codex FAIL "codex $ver is below the $MIN_CODEX_CLI_VERSION the wrapper enforces. Upgrade: npm install -g @openai/codex."
    return 1
  fi
  report codex PASS "codex $ver (>= $MIN_CODEX_CLI_VERSION)"
  return 0
}

chk_pwsh() {
  local uname_s
  if [[ "$PHASE" == "build" ]]; then
    report pwsh SKIP "phase=build"
    return 0
  fi
  uname_s="$(uname -s 2>/dev/null || echo unknown)"
  if command -v pwsh >/dev/null 2>&1; then
    report pwsh PASS "$(command -v pwsh)"
    return 0
  fi
  case "$uname_s" in
    MINGW*|MSYS*|CYGWIN*)
      if command -v powershell >/dev/null 2>&1; then
        report pwsh PASS "$(command -v powershell) (Windows PowerShell; pwsh not installed)"
        return 0
      fi
      report pwsh FAIL "neither pwsh nor powershell on PATH on Windows, where Invoke-CodexDispatch.ps1 is the canonical wrapper."
      return 1 ;;
    *)
      # A warning, not a failure: macOS/Linux has Invoke-CodexDispatch.sh as the canonical
      # wrapper, and ADOPTION-QUESTIONS A4b says to assume pwsh is absent there.
      report pwsh WARN "pwsh absent on $uname_s. Use tools/Invoke-CodexDispatch.sh; the .ps1 twin and Test-CliDispatch.ps1 cannot run here."
      return 0 ;;
  esac
}

chk_sync() {
  # A cloud-sync daemon is a second writer: it can move a receipt mid-read, and it can
  # upload one. Named paths only -- guessing from mount tables produced false positives.
  local root dir hits="" p
  root="$(repo_root)"
  dir="${RECEIPTS_DIR:-$DEFAULT_RECEIPTS_DIR}"
  for p in "$root" "$dir"; do
    case "$p" in
      *[Gg]oogle[\ ]*[Dd]rive*|*GoogleDrive*|*CloudStorage*|*OneDrive*|*[Dd]ropbox*|*com~apple~CloudDocs*|*iCloud*)
        hits="$hits $p" ;;
    esac
  done
  if [[ -n "$hits" ]]; then
    report sync WARN "inside a cloud-sync working copy:$hits. Answer ADOPTION-QUESTIONS A4c per path: move receipts to local disk, or expect a second writer during file-settling waits."
    return 0
  fi
  report sync PASS "repo and receipts are not under a known sync root"
  return 0
}

ALL_CHECKS="receipts rg python registry git codex pwsh sync"

run_checks() {
  local name
  for name in $ALL_CHECKS; do
    if [[ -n "$ONLY" && "$ONLY" != "$name" ]]; then continue; fi
    "chk_$name" || true
  done
}

# ---------------------------------------------------------------------------
# selftest -- every check must be shown able to fail, and able to pass
# ---------------------------------------------------------------------------

# Arms re-invoke THIS script with --only, in a subprocess with a mutated environment, so
# each arm exercises the real entry point rather than a reimplementation of the rule (V2).
# A check that cannot fail is not a check; a suite with no must-pass arm is equally
# satisfied by a script that refuses everything (V3/V5).
selftest() {
  local arms=0 fails=0 musts=0 tmp stub bash_bin rd_token
  tmp="$(make_temp_dir)" || fail_closed "no scratch directory, so the selftest could not run. Exit 3: this is not a passing suite."
  # Absolute, because several arms strip PATH: `env PATH=/empty bash ...` resolves the
  # command *after* applying the new environment, so a bare `bash` would not be found and
  # the arm would exit 127 -- passing a "must refuse" arm for entirely the wrong reason.
  bash_bin="$(command -v bash)"
  [[ -x "$bash_bin" ]] || fail_closed "cannot locate the bash binary by absolute path, so the selftest cannot re-invoke this script with a mutated PATH."

  arm() {
    # arm LABEL EXPECT_EXIT MUST_SAY [ENV_ASSIGNMENT...] -- [SCRIPT_ARG...]
    #
    # MUST_SAY ("" to skip) is what makes an arm test a *clause* rather than a mood: eight
    # checks all exit 1, so an exit-code-only arm passes when the wrong rule fired -- and
    # "receipts is relative" passing because the placeholder guard caught it first is
    # exactly the drift this suite exists to catch.
    #
    # Split at `--` here rather than handing the whole list to env: env would take
    # `--` as its own end-of-options marker and then try to exec `--only`.
    local label="$1" want="$2" needle="$3"; shift 3
    local got out a seen=0
    local envs=() args=()
    for a in "$@"; do
      if [[ $seen -eq 0 && "$a" == "--" ]]; then seen=1; continue; fi
      if [[ $seen -eq 0 ]]; then envs+=("$a"); else args+=("$a"); fi
    done
    # The `[@]+` guard is what makes an empty array safe under `set -u` in bash 3.2.
    out="$(env ${envs[@]+"${envs[@]}"} "$bash_bin" "$0" ${args[@]+"${args[@]}"} 2>&1)"; got=$?
    arms=$((arms + 1))
    if [[ "$want" == "0" ]]; then musts=$((musts + 1)); fi
    if [[ "$got" != "$want" ]]; then
      printf 'FAIL %-38s want exit %s, got %s: %s\n' "$label" "$want" "$got" \
        "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-150)"
      fails=$((fails + 1))
      return 0
    fi
    if [[ -n "$needle" && "$out" != *"$needle"* ]]; then
      printf 'FAIL %-38s exit %s as expected but never said %s: %s\n' "$label" "$got" \
        "\"$needle\"" "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-150)"
      fails=$((fails + 1))
      return 0
    fi
    printf 'PASS %-38s exit %s\n' "$label" "$got"
  }

  arm_bounded() {
    # Same contract as `arm`, but the child is killed if it does not terminate. Used for
    # the missing-operand arms: the bug they cover was an infinite loop, and an unbounded
    # arm for a hang *hangs the suite* rather than failing it -- a suite that never
    # returns is indistinguishable from one still working, which is the worst of both.
    # `timeout` is not on a stock macOS, so this polls instead.
    local label="$1" want="$2" needle="$3"; shift 3
    local pid got out waited=0
    out="$tmp/bounded.out"
    "$bash_bin" "$0" "$@" >"$out" 2>&1 &
    pid=$!
    while kill -0 "$pid" 2>/dev/null; do
      if (( waited >= 50 )); then          # 50 x 0.1s = 5s
        kill -9 "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        arms=$((arms + 1)); fails=$((fails + 1))
        printf 'FAIL %-38s did not terminate within 5s (a usage error must exit, not stall)\n' "$label"
        return 0
      fi
      sleep 0.1
      waited=$((waited + 1))
    done
    wait "$pid"; got=$?
    arms=$((arms + 1))
    if [[ "$want" == "0" ]]; then musts=$((musts + 1)); fi
    if [[ "$got" != "$want" ]]; then
      printf 'FAIL %-38s want exit %s, got %s: %s\n' "$label" "$want" "$got" \
        "$(tr '\n' ' ' <"$out" | cut -c1-150)"
      fails=$((fails + 1))
      return 0
    fi
    if [[ -n "$needle" ]] && ! grep -q -- "$needle" "$out"; then
      printf 'FAIL %-38s exit %s as expected but never said "%s"\n' "$label" "$got" "$needle"
      fails=$((fails + 1))
      return 0
    fi
    printf 'PASS %-38s exit %s\n' "$label" "$got"
  }

  # -- receipts ------------------------------------------------------------
  # Assembled at runtime from pieces. Written literally, instantiate.py substituted this
  # *fixture* on install: the arm received a valid absolute path, the negative arm quietly
  # became a positive one, and the suite failed on the only trees that matter -- adopters'.
  rd_token="$(printf '%s%s%s' '{{' 'RECEIPTS_DIR' '}}')"
  arm "receipts-placeholder-refused" 1 "uninstantiated token" \
    RECEIPTS_DIR="$rd_token" -- --only receipts
  arm "receipts-relative-refused" 1 "is relative" \
    RECEIPTS_DIR="relative/receipts" -- --only receipts
  arm "receipts-inside-repo-refused" 1 "is inside the repo" \
    RECEIPTS_DIR="$(repo_root)/receipts" -- --only receipts
  arm "receipts-temp-ok" 0 "receipts  PASS" \
    RECEIPTS_DIR="$tmp/receipts" -- --only receipts

  # -- rg ------------------------------------------------------------------
  # An empty directory on PATH, not `PATH=`: an empty PATH removes bash's own helpers too,
  # so a refusal would prove nothing about rg. This way the stub dir is the only entry
  # that could supply rg, and it does not.
  mkdir -p "$tmp/nopath"
  arm "rg-absent-refused" 1 "is not on PATH" PATH="$tmp/nopath" -- --only rg
  # rg present but unable to match -- the case a presence-only check calls healthy, after
  # which every "no output means clean" sweep in the package reports clean.
  stub="$tmp/blindrg"; mkdir -p "$stub"
  printf '#!/bin/sh\nexit 1\n' >"$stub/rg"; chmod +x "$stub/rg"
  printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v mktemp)" >"$stub/mktemp"; chmod +x "$stub/mktemp"
  printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v rm)" >"$stub/rm"; chmod +x "$stub/rm"
  arm "rg-that-cannot-match-refused" 1 "exit 1 = no match" PATH="$stub" -- --only rg
  # The arm the merged-stream version could not have: rg fails, but its *error message*
  # contains the canary. Under `2>&1` that was indistinguishable from a match, so this
  # stub used to be reported PASS. The status now decides.
  stub="$tmp/noisyrg"; mkdir -p "$stub"
  printf '#!/bin/sh\necho "rg: error while searching for PREFLIGHT-CANARY-STRING" >&2\nexit 2\n' \
    >"$stub/rg"; chmod +x "$stub/rg"
  printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v mktemp)" >"$stub/mktemp"; chmod +x "$stub/mktemp"
  printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v rm)" >"$stub/rm"; chmod +x "$stub/rm"
  arm "rg-canary-on-stderr-still-refused" 1 "an error, not a no-match" PATH="$stub" -- --only rg
  arm "rg-real-ok" 0 "matched a known fixture" -- --only rg

  # -- scratch-directory propagation ---------------------------------------
  # A mktemp that prints a usable path and then fails. The old code ran fail_closed inside
  # `$(...)`, so `exit 3` killed only the subshell: preflight printed FAIL-CLOSED on stderr
  # and exited 0. This arm asserts the parent now carries the 3 out.
  stub="$tmp/badmktemp"; mkdir -p "$stub"
  printf '#!/bin/sh\nmkdir -p "%s/decoy"\nprintf "%s/decoy\\n"\nexit 1\n' "$tmp" "$tmp" \
    >"$stub/mktemp"; chmod +x "$stub/mktemp"
  printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v rg)" >"$stub/rg"; chmod +x "$stub/rg"
  arm "scratch-failure-propagates-as-3" 3 "FAIL-CLOSED" \
    PATH="$stub:$PATH" -- --only rg

  # -- python --------------------------------------------------------------
  arm "python-absent-refused" 1 "neither python3 nor python" PATH="$tmp/nopath" -- --only python
  arm "python-real-ok" 0 "pyyaml + jsonschema" -- --only python

  # -- registry ------------------------------------------------------------
  # A home that exists but holds no registry file: the failure mode of checking for the
  # directory alone, which is how a machine passes preflight and then cannot resolve a class.
  mkdir -p "$tmp/emptyhome"
  arm "registry-dir-without-file-refused" 1 "has no model-registry" \
    AGENT_MODEL_REGISTRY= AGENT_MODEL_REGISTRY_HOME="$tmp/emptyhome" -- --only registry
  arm "registry-absent-home-refused" 1 "does not exist" \
    AGENT_MODEL_REGISTRY= AGENT_MODEL_REGISTRY_HOME="$tmp/nosuchhome" -- --only registry
  mkdir -p "$tmp/goodhome"; printf '{}\n' >"$tmp/goodhome/model-registry.json"
  arm "registry-resolves-ok" 0 "via AGENT_MODEL_REGISTRY_HOME" \
    AGENT_MODEL_REGISTRY= AGENT_MODEL_REGISTRY_HOME="$tmp/goodhome" -- --only registry
  # A home holding only the YAML *source*. The resolver reads compiled JSON, so accepting
  # this passed a machine that could then not resolve a single class -- and the message has
  # to name the real remedy ("compile it"), not "the registry is missing".
  mkdir -p "$tmp/yamlonly"; printf 'models: {}\n' >"$tmp/yamlonly/model-registry.yaml"
  arm "registry-yaml-without-compiled-refused" 1 "no compiled model-registry.json" \
    AGENT_MODEL_REGISTRY= AGENT_MODEL_REGISTRY_HOME="$tmp/yamlonly" -- --only registry
  # The two rungs take different kinds of path (S2). Both directions are asserted, because
  # the bug was one-sided: a valid *file* override was refused as a missing home.
  arm "registry-file-override-ok" 0 "via AGENT_MODEL_REGISTRY)" \
    AGENT_MODEL_REGISTRY="$tmp/goodhome/model-registry.json" \
    AGENT_MODEL_REGISTRY_HOME="$tmp/emptyhome" -- --only registry
  arm "registry-dir-in-file-rung-refused" 1 "is a directory, but that rung names" \
    AGENT_MODEL_REGISTRY="$tmp/goodhome" -- --only registry
  arm "registry-noncompiled-file-override-refused" 1 "is not a .json file" \
    AGENT_MODEL_REGISTRY="$tmp/yamlonly/model-registry.yaml" -- --only registry

  # -- git -----------------------------------------------------------------
  arm "git-absent-refused" 1 "git is not on PATH" PATH="$tmp/nopath" -- --only git

  # -- sync ----------------------------------------------------------------
  # A warning, so both arms expect exit 0 and the needle is doing all the work: an
  # exit-code-only pair here would be satisfied by a check that never looked.
  mkdir -p "$tmp/Dropbox/receipts"
  arm "sync-warns-inside-cloud-copy" 0 "cloud-sync working copy" \
    RECEIPTS_DIR="$tmp/Dropbox/receipts" -- --only sync
  arm "sync-quiet-on-local-disk" 0 "not under a known sync root" \
    RECEIPTS_DIR="$tmp/receipts" -- --only sync

  # -- phase ---------------------------------------------------------------
  # A phase flag that skipped everything would satisfy every must-refuse arm above, so the
  # skip is asserted in both directions: skipped under build, and *run* under review.
  arm "codex-skipped-when-phase-build" 0 "codex     SKIP" -- --phase build --only codex
  arm "receipts-still-runs-when-phase-build" 1 "is relative" \
    RECEIPTS_DIR="relative/receipts" -- --phase build --only receipts

  # -- usage ---------------------------------------------------------------
  arm "unknown-phase-is-usage" 2 "--phase must be" -- --phase sideways
  arm "unknown-check-is-usage" 2 "--only must name" -- --only nonesuch
  # Bounded, because the defect these cover was a hang: `shift 2` with one argument left
  # shifts nothing and returns non-zero, so the parser re-read the same flag forever.
  arm_bounded "only-without-operand-is-usage" 2 "--only requires a value" --only
  arm_bounded "phase-without-operand-is-usage" 2 "--phase requires a value" --phase

  rm -rf "$tmp"
  printf '\n'
  if (( fails > 0 )); then
    printf 'REFUSE: %d arm(s), %d failure(s)\n' "$arms" "$fails"
    return 1
  fi
  printf 'OK: %d arm(s), 0 failure(s) [%d must-pass arms, so the script is not refusing everything]\n' \
    "$arms" "$musts"
  return 0
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --phase|--only)
      # `shift 2` with one argument remaining shifts *nothing* and returns non-zero, so
      # the loop re-read the same flag forever: `preflight.sh --only` hung until killed.
      # A usage error has to terminate the process -- an automation harness waiting on
      # this pid cannot tell a stall from a slow check, and neither can a person.
      if [[ $# -lt 2 || -z "$2" ]]; then
        printf 'USAGE: %s requires a value\n' "$1" >&2
        usage >&2
        exit 2
      fi
      case "$1" in
        --phase) PHASE="$2" ;;
        --only)  ONLY="$2" ;;
      esac
      shift 2 ;;
    --selftest) SELFTEST=1; shift ;;
    *) printf 'USAGE: unknown argument %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$PHASE" in
  all|build|review) ;;
  *) printf 'USAGE: --phase must be all, build, or review (got %s)\n' "$PHASE" >&2; exit 2 ;;
esac

if [[ -n "$ONLY" ]]; then
  case " $ALL_CHECKS " in
    *" $ONLY "*) ;;
    *) printf 'USAGE: --only must name one of: %s (got %s)\n' "$ALL_CHECKS" "$ONLY" >&2; exit 2 ;;
  esac
fi

if (( SELFTEST )); then
  selftest
  exit $?
fi

printf 'preflight (phase=%s)\n' "$PHASE"
run_checks

if (( PASS_COUNT + FAIL_COUNT + WARN_COUNT + SKIP_COUNT == 0 )); then
  # Nothing ran at all, which is not the same as nothing being wrong (V4). A deliberate
  # skip does count as having run -- it is reported by name, so it cannot hide -- but a
  # run where no check even dispatched means the selection logic is broken.
  fail_closed "no check ran (phase=$PHASE, only='$ONLY'). A preflight that checks nothing must not report OK."
fi

if (( FAIL_COUNT > 0 )); then
  printf 'REFUSE: %d prerequisite(s) missing:%s (%d passed, %d warning(s), %d skipped)\n' \
    "$FAIL_COUNT" "$FAIL_NAMES" "$PASS_COUNT" "$WARN_COUNT" "$SKIP_COUNT"
  exit 1
fi
printf 'OK: %d check(s) passed, %d warning(s), %d skipped (phase=%s)\n' \
  "$PASS_COUNT" "$WARN_COUNT" "$SKIP_COUNT" "$PHASE"
exit 0
