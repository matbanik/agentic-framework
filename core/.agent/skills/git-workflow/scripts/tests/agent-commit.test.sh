#!/usr/bin/env bash
# agent-commit.test.sh -- the exact-scope mode of agent-commit.sh (B-9; AC-I.1, FS row 83).
#
# The POSIX twin of the agent-commit.ps1 tests: exact-scope mode hands each phase
# (candidate, publish, index) to `tools.commit_batch` under the tree's gate lease and
# prints the driver's JSON. It refuses a bad --phase (usage, exit 2), a run without
# --no-push and a run without the commit grant (refused, exit 1), stops at the first
# failing phase with that phase's exit code, and refuses `lease_held` while another
# holder has the lease, unless the run carries the holder's own token (nested).
#
# The lease is the executor lease's protocol: `<git dir>/{{PROJECT_NAME}}-gate.lock`,
# never deleted, an exclusive `flock` while held, a JSON body with a 32-hex `token`, and
# the token in {{PROJECT_NAME_UPPER}}_GATE_LEASE_TOKEN for the children.
#
# Needs bash, git and flock(1) only; the driver is a stub. Prints one ok/FAILED line per
# case and exits 1 when any case fails.
#
#   bash core/.agent/skills/git-workflow/scripts/tests/agent-commit.test.sh

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../agent-commit.sh"
UPPER='{{PROJECT_NAME_UPPER}}'
NAME='{{PROJECT_NAME}}'
GRANT_ENV="${UPPER}_COMMIT_GRANT"
PYTHON_ENV="${UPPER}_PYTHON"
TOKEN_ENV="${UPPER}_GATE_LEASE_TOKEN"

for tool in git flock; do
    command -v "$tool" >/dev/null 2>&1 || { echo "FAILED setup: $tool not on PATH"; exit 1; }
done
[ -f "$SCRIPT" ] || { echo "FAILED setup: missing $SCRIPT"; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/agent-commit-test.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT
FAILURES=0

# -- the driver stub: logs its step, the inherited token, the lease state and body ------

STUB="$TMP/python"
cat >"$STUB" <<STUB_EOF
#!/usr/bin/env bash
step=""; prev=""
for a in "\$@"; do
    [ "\$prev" = "--step" ] && step="\$a"
    prev="\$a"
done
token="\$(printenv '$TOKEN_ENV' || true)"
if flock -n "\$STUB_LEASE" true; then lease=free; else lease=busy; fi
body="\$(tr -d '\n' <"\$STUB_LEASE")"
printf 'step=%s|token=%s|lease=%s|body=%s|args=%s\n' "\$step" "\$token" "\$lease" "\$body" "\$*" >>"\$STUB_LOG"
printf '{"result":"ok","phase":"%s","commit":"c0ffee","parent":"p","tree":"t","paths":["a.txt"]}\n' "\$step"
if [ "\${STUB_EXIT_AT-}" = "\$step" ]; then exit 5; fi
exit 0
STUB_EOF
chmod +x "$STUB"

# -- helpers -----------------------------------------------------------------------------

fresh() {
    # A new repo, log and lease path for one case.
    CASE_DIR="$TMP/$1"
    REPO="$CASE_DIR/repo"
    LOG="$CASE_DIR/calls.log"
    OUT="$CASE_DIR/out.txt"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    LEASE="$(git -C "$REPO" rev-parse --absolute-git-dir)/${NAME}-gate.lock"
    : >"$LOG"
}

run_script() {
    # run_script <grant|nogrant> <token|-> <args...>: exact-scope mode against the stub.
    local grant="$1" token="$2"
    shift 2
    local -a envs
    envs=(-u "$GRANT_ENV" -u "$TOKEN_ENV" "$PYTHON_ENV=$STUB" "STUB_LOG=$LOG" "STUB_LEASE=$LEASE")
    [ "$grant" = grant ] && envs=("${envs[@]}" "$GRANT_ENV=op-1")
    [ "$token" != - ] && envs=("${envs[@]}" "$TOKEN_ENV=$token")
    (cd "$CASE_DIR" && env "${envs[@]}" bash "$SCRIPT" --repository-path "$REPO" "$@") >"$OUT" 2>"$CASE_DIR/err.txt"
    CODE=$?
}

steps() { sed -n 's/^step=\([^|]*\)|.*/\1/p' "$LOG" | tr '\n' ' ' | sed 's/ $//'; }
field() { sed -n "s/.*|$1=\([^|]*\)|.*/\1/p" "$LOG"; }
calls() { grep -c '^step=' "$LOG" || true; }

hold_lease() {
    # hold_lease <token>: take the lease on fd 8 as another tool would, then write its body.
    exec 8>>"$LEASE"
    flock -n 8 || { echo "FAILED setup: lease already held"; exit 1; }
    printf '{"schema": 1, "pid": %d, "token": "%s"}' "$$" "$1" >"$LEASE"
}
release_lease() { flock -u 8; exec 8>&-; }
lease_free() { flock -n "$LEASE" true; }

check() {
    # check <case> <condition text> <status>: record one assertion.
    if [ "$3" -eq 0 ]; then
        return 0
    fi
    echo "FAILED $1: $2 (exit=$CODE)"
    sed 's/^/    out: /' "$OUT"
    sed 's/^/    err: /' "$CASE_DIR/err.txt"
    FAILURES=$((FAILURES + 1))
    CASE_FAILED=1
}

begin() { CASE="$1"; CASE_FAILED=0; fresh "$1"; }
end() { [ "$CASE_FAILED" -eq 0 ] && echo "ok $CASE"; }

# -- cases -------------------------------------------------------------------------------

begin bad-phase-is-usage
run_script grant - --no-push --phase bogus
[ "$CODE" -eq 2 ]; check "$CASE" "exit 2" $?
grep -q '"reason":"phase"' "$OUT"; check "$CASE" '"reason":"phase"' $?
[ "$(calls)" -eq 0 ]; check "$CASE" "the driver is not called" $?
end

begin push-is-refused
run_script grant -
[ "$CODE" -eq 1 ]; check "$CASE" "exit 1" $?
grep -q '"reason":"push"' "$OUT"; check "$CASE" '"reason":"push"' $?
[ "$(calls)" -eq 0 ]; check "$CASE" "the driver is not called" $?
end

begin no-grant-is-refused
run_script nogrant - --no-push
[ "$CODE" -eq 1 ]; check "$CASE" "exit 1" $?
grep -q '"reason":"grant"' "$OUT"; check "$CASE" '"reason":"grant"' $?
[ "$(calls)" -eq 0 ]; check "$CASE" "the driver is not called" $?
end

begin three-phases-in-order
run_script grant - --no-push
[ "$CODE" -eq 0 ]; check "$CASE" "exit 0" $?
[ "$(steps)" = "candidate publish index" ]; check "$CASE" "steps candidate publish index, got '$(steps)'" $?
[ "$(grep -c -- "-m tools.commit_batch --repo $REPO --step " "$LOG")" -eq 3 ]; check "$CASE" "each call is -m tools.commit_batch --repo <repo> --step <phase>" $?
[ "$(grep -c '"commit":"c0ffee"' "$OUT")" -eq 3 ]; check "$CASE" "the driver's JSON is echoed per phase" $?
end

begin single-phase
run_script grant - --no-push --phase publish
[ "$CODE" -eq 0 ]; check "$CASE" "exit 0" $?
[ "$(steps)" = "publish" ]; check "$CASE" "only publish runs, got '$(steps)'" $?
end

begin stops-at-the-failing-phase
STUB_EXIT_AT=publish run_script grant - --no-push
[ "$CODE" -eq 5 ]; check "$CASE" "the failing phase's exit code 5" $?
[ "$(steps)" = "candidate publish" ]; check "$CASE" "index does not run, got '$(steps)'" $?
end

begin exact-arguments-map
for f in manifest.json message.txt descriptor.json; do printf '{}\n' >"$CASE_DIR/$f"; done
run_script grant - --no-push --phase candidate --expected-base B1 --expected-tree T1 \
    --scope-manifest "$CASE_DIR/manifest.json" --message-file "$CASE_DIR/message.txt" \
    --content-descriptor "$CASE_DIR/descriptor.json"
[ "$CODE" -eq 0 ]; check "$CASE" "exit 0" $?
args="$(sed -n 's/.*|args=//p' "$LOG")"
for want in "--expect-base B1" "--expect-tree T1" "--scope-manifest $CASE_DIR/manifest.json" \
    "--message-file $CASE_DIR/message.txt" "--descriptor $CASE_DIR/descriptor.json"; do
    case "$args" in *"$want"*) true ;; *) false ;; esac
    check "$CASE" "args carry '$want', got '$args'" $?
done
end

begin lease-held-during-the-phases
run_script grant - --no-push
[ "$CODE" -eq 0 ]; check "$CASE" "exit 0" $?
[ "$(field lease | sort -u)" = "busy" ]; check "$CASE" "the lease is held during every phase" $?
tokens="$(field token | sort -u)"
[ "$(printf '%s\n' "$tokens" | wc -l | tr -d ' ')" -eq 1 ]; check "$CASE" "one token for the run" $?
printf '%s' "$tokens" | grep -Eq '^[0-9a-f]{32}$'; check "$CASE" "the token is 32 hex, got '$tokens'" $?
body="$(sed -n '1s/.*|body=\([^|]*\)|.*/\1/p' "$LOG")"
case "$body" in *"$tokens"*) true ;; *) false ;; esac; check "$CASE" "the body carries the token, got '$body'" $?
[ -f "$LEASE" ]; check "$CASE" "the lease file is never deleted" $?
lease_free; check "$CASE" "the lease is released after the run" $?
end

begin lease-held-by-another
hold_lease aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
run_script grant - --no-push
release_lease
[ "$CODE" -eq 1 ]; check "$CASE" "exit 1" $?
grep -q '"reason":"lease_held"' "$OUT"; check "$CASE" '"reason":"lease_held"' $?
[ "$(calls)" -eq 0 ]; check "$CASE" "the driver is not called" $?
end

begin wrong-token-is-lease-held
hold_lease aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
run_script grant bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb --no-push
release_lease
[ "$CODE" -eq 1 ]; check "$CASE" "exit 1" $?
grep -q '"reason":"lease_held"' "$OUT"; check "$CASE" '"reason":"lease_held"' $?
[ "$(calls)" -eq 0 ]; check "$CASE" "the driver is not called" $?
end

begin holders-token-runs-nested
hold_lease cccccccccccccccccccccccccccccccc
before="$(cat "$LEASE")"
run_script grant cccccccccccccccccccccccccccccccc --no-push
after="$(cat "$LEASE")"
release_lease
[ "$CODE" -eq 0 ]; check "$CASE" "exit 0" $?
[ "$(steps)" = "candidate publish index" ]; check "$CASE" "the phases run nested, got '$(steps)'" $?
[ "$(field token | sort -u)" = "cccccccccccccccccccccccccccccccc" ]; check "$CASE" "the children keep the holder's token" $?
[ "$before" = "$after" ]; check "$CASE" "the holder's body is untouched" $?
end

begin output-state-is-written
printf '{}\n' >"$CASE_DIR/descriptor.json"
run_script grant - --no-push --content-descriptor "$CASE_DIR/descriptor.json" --output-state "$CASE_DIR/state.json"
[ "$CODE" -eq 0 ]; check "$CASE" "exit 0" $?
[ -f "$CASE_DIR/state.json" ] && grep -q 'c0ffee' "$CASE_DIR/state.json"; check "$CASE" "state.json carries the commit" $?
end

if [ "$FAILURES" -ne 0 ]; then
    echo "FAILED: $FAILURES assertion(s)"
    exit 1
fi
echo "ALL OK"
exit 0
