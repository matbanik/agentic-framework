#!/usr/bin/env bash
# agent-commit.sh -- POSIX/macOS companion to agent-commit.ps1.
#
# Same contract as the PowerShell script: never open an editor, never rebase
# interactively, never pass --no-verify. Two modes:
#
#   legacy       validate signing -> stage -> lint/test -> commit -> push -> verify
#   exact-scope  commit ONLY an approved manifest, in an isolated index, against
#                an approved parent/tree/message/signing fingerprint
#
# Written for bash 3.2 -- the version Apple ships. No mapfile, no associative
# arrays, no ${var,,}. Test any change against bash 3.2 semantics, not just the
# bash 5 on your Linux box.
#
# Usage
#   agent-commit.sh --message "feat: description" [--body TEXT]
#                   [--branch NAME] [--no-push] [--skip-tests]
#
#   agent-commit.sh --repository-path DIR --scope-manifest FILE \
#                   --expected-base SHA --expected-tree SHA \
#                   --content-descriptor FILE --message-file FILE \
#                   --output-state FILE --no-push
#
# Exit codes
#   0 success (including "nothing to commit")
#   1 a gate refused: signing config, lint, tests, commit, push, drift
#   2 bad invocation (unknown flag, missing required argument)
#   3 a required host tool is absent, so a check could not be performed
#
# Note 3 is distinct from 1 on purpose. "The gate said no" and "the gate could
# not run" are different facts, and collapsing them is how a repo ends up
# believing an unrun check passed.

set -euo pipefail

# --------------------------------------------------------------------------
# Hang prevention. The PowerShell script only *warns* about an HTTPS remote;
# here we make the failure mode deterministic instead. GIT_TERMINAL_PROMPT=0
# turns a credential prompt into an immediate non-zero exit, and GIT_EDITOR=true
# turns "some command wants an editor" into a no-op rather than a stalled
# process holding the agent's turn open forever. Both are belt-and-braces: no
# command below is supposed to need either.
# --------------------------------------------------------------------------
export GIT_TERMINAL_PROMPT=0
export GIT_EDITOR=true

if [ -t 1 ]; then
    C_RESET=$'\033[0m'; C_CYAN=$'\033[36m'; C_YELLOW=$'\033[33m'
    C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_DIM=$'\033[2m'
else
    C_RESET=""; C_CYAN=""; C_YELLOW=""; C_GREEN=""; C_RED=""; C_DIM=""
fi

step() { printf '%s%s%s\n' "$C_YELLOW" "$*" "$C_RESET"; }
ok()   { printf '  %s%s%s\n' "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
die()  { printf '%sERROR: %s%s\n' "$C_RED" "$*" "$C_RESET" >&2; exit 1; }
die_toolless() { printf '%sUNAVAILABLE: %s%s\n' "$C_RED" "$*" "$C_RESET" >&2; exit 3; }
usage_error() {
    printf '%sUSAGE: %s%s\n' "$C_RED" "$*" "$C_RESET" >&2
    printf 'See the header of this script, or .agent/skills/git-workflow/SKILL.md\n' >&2
    exit 2
}

# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------
MESSAGE=""
BODY=""
BRANCH="main"
NO_PUSH=0
SKIP_TESTS=0
REPOSITORY_PATH=""
SCOPE_MANIFEST=""
EXPECTED_BASE=""
EXPECTED_TREE=""
CONTENT_DESCRIPTOR=""
MESSAGE_FILE=""
OUTPUT_STATE=""
SELFTEST=0

need_value() {
    # $1 = flag name, $2 = value (may be unset)
    if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        usage_error "$1 requires a value"
    fi
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --message)            need_value "$1" "${2-}"; MESSAGE="$2"; shift 2 ;;
        --body)               need_value "$1" "${2-}"; BODY="$2"; shift 2 ;;
        --branch)             need_value "$1" "${2-}"; BRANCH="$2"; shift 2 ;;
        --no-push)            NO_PUSH=1; shift ;;
        --skip-tests)         SKIP_TESTS=1; shift ;;
        --repository-path)    need_value "$1" "${2-}"; REPOSITORY_PATH="$2"; shift 2 ;;
        --scope-manifest)     need_value "$1" "${2-}"; SCOPE_MANIFEST="$2"; shift 2 ;;
        --expected-base)      need_value "$1" "${2-}"; EXPECTED_BASE="$2"; shift 2 ;;
        --expected-tree)      need_value "$1" "${2-}"; EXPECTED_TREE="$2"; shift 2 ;;
        --content-descriptor) need_value "$1" "${2-}"; CONTENT_DESCRIPTOR="$2"; shift 2 ;;
        --message-file)       need_value "$1" "${2-}"; MESSAGE_FILE="$2"; shift 2 ;;
        --output-state)       need_value "$1" "${2-}"; OUTPUT_STATE="$2"; shift 2 ;;
        --selftest)           SELFTEST=1; shift ;;
        -h|--help)            sed -n '2,30p' "$0"; exit 0 ;;
        # An unknown flag is never ignored. The PowerShell examples in SKILL.md
        # use -Message / -NoPush; someone who copies one of those into this
        # script must get a loud refusal, not a commit with default settings.
        *)                    usage_error "unknown argument: $1" ;;
    esac
done

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

#: The git invocation. The originating repo routes exact-scope git through a
#: guarded proxy (`rtk proxy git`); an adopter without one gets plain git. Set
#: AGENT_GIT_PROXY to that proxy's argv prefix -- e.g. AGENT_GIT_PROXY="rtk proxy"
#: -- and every git call below goes through it. Unset is the normal case.
#: stderr is deliberately NOT captured: several callers use the return value as a
#: SHA, and folding a git warning into that string would produce a comparison
#: against a corrupted value rather than a clean mismatch. Diagnostics go to the
#: terminal where a human reads them.
git_x() {
    local repo="$1"; shift
    local out status
    set +e
    # shellcheck disable=SC2086  # AGENT_GIT_PROXY is an argv prefix; word-split is the point.
    out="$(${AGENT_GIT_PROXY-} git -C "$repo" "$@")"
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        die "git command failed with exit code $status: git $*"
    fi
    printf '%s' "$out"
}

#: A git config read whose absence is a condition to report, not a crash. git
#: exits 1 for "key not set", which git_x would turn into an opaque failure and
#: skip the specific message the caller wants to print.
git_config_opt() {
    local repo="$1" key="$2"
    ${AGENT_GIT_PROXY-} git -C "$repo" config --get "$key" 2>/dev/null || true
}

sha256_file() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print tolower($1)}'
    elif command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print tolower($1)}'
    else
        die_toolless "no shasum or sha256sum on PATH; cannot hash $1"
    fi
}

#: Read one scalar field out of the content descriptor. Bash cannot parse JSON,
#: and hand-rolling a regex for a file whose whole job is to be authoritative
#: would be the wrong kind of clever. python3 first (present on any machine that
#: can run this package's other tooling), jq second, fail closed third.
json_field() {
    local file="$1" key="$2"
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
v=d.get(sys.argv[2])
sys.stdout.write("" if v is None else str(v))' "$file" "$key"
    elif command -v jq >/dev/null 2>&1; then
        jq -r --arg k "$key" '.[$k] // "" | tostring' "$file"
    else
        die_toolless "exact-scope mode needs python3 or jq to read $file"
    fi
}

emit_state() {
    # $1=out $2=sha $3=parent $4=tree $5=descriptor_sha $6=scope-file (one path/line)
    if command -v python3 >/dev/null 2>&1; then
        python3 -c 'import json,sys
out,sha,parent,tree,dsha,scopefile=sys.argv[1:7]
scope=[l.rstrip("\n") for l in open(scopefile,encoding="utf-8") if l.strip()]
state={"schema_version":1,"actual_sha":sha,"parent":parent,"tree":tree,
       "signature_verified":True,"content_descriptor_sha256":dsha,"scope":scope}
open(out,"w",encoding="utf-8").write(json.dumps(state,indent=2)+"\n")' \
            "$1" "$2" "$3" "$4" "$5" "$6"
    elif command -v jq >/dev/null 2>&1; then
        jq -n --arg sha "$2" --arg parent "$3" --arg tree "$4" --arg dsha "$5" \
              --rawfile scope "$6" \
              '{schema_version:1, actual_sha:$sha, parent:$parent, tree:$tree,
                signature_verified:true, content_descriptor_sha256:$dsha,
                scope:($scope|split("\n")|map(select(length>0)))}' > "$1"
    else
        die_toolless "exact-scope mode needs python3 or jq to write $1"
    fi
}

abspath() {
    # Resolve without requiring GNU readlink -f (absent on stock macOS).
    if [ -d "$1" ]; then
        (cd "$1" && pwd -P)
    elif [ -e "$1" ]; then
        local dir base
        dir="$(dirname "$1")"; base="$(basename "$1")"
        printf '%s/%s' "$(cd "$dir" && pwd -P)" "$base"
    else
        die "path does not exist: $1"
    fi
}

# --------------------------------------------------------------------------
# Exact-scope signed commit mode
# --------------------------------------------------------------------------
exact_scope_commit() {
    local missing=""
    [ -n "$REPOSITORY_PATH" ]    || missing="$missing --repository-path"
    [ -n "$SCOPE_MANIFEST" ]     || missing="$missing --scope-manifest"
    [ -n "$EXPECTED_BASE" ]      || missing="$missing --expected-base"
    [ -n "$EXPECTED_TREE" ]      || missing="$missing --expected-tree"
    [ -n "$CONTENT_DESCRIPTOR" ] || missing="$missing --content-descriptor"
    [ -n "$MESSAGE_FILE" ]       || missing="$missing --message-file"
    [ -n "$OUTPUT_STATE" ]       || missing="$missing --output-state"
    if [ -n "$missing" ]; then
        usage_error "exact-scope mode requires all seven bindings; missing:$missing"
    fi
    if [ "$NO_PUSH" -ne 1 ]; then
        die "exact-scope mode requires --no-push; pushing is a separate approved checkpoint"
    fi

    local repo manifest descriptor message_path
    repo="$(abspath "$REPOSITORY_PATH")"
    manifest="$(abspath "$SCOPE_MANIFEST")"
    descriptor="$(abspath "$CONTENT_DESCRIPTOR")"
    message_path="$(abspath "$MESSAGE_FILE")"

    local current_base
    current_base="$(git_x "$repo" rev-parse HEAD)"
    if [ "$current_base" != "$EXPECTED_BASE" ]; then
        die "exact-scope base drift: expected $EXPECTED_BASE, got $current_base"
    fi

    # ---- Manifest: every path relative, POSIX, inside the repo, present, unique.
    local scope_file seen path folded count
    scope_file="$(mktemp "${TMPDIR:-/tmp}/agent-commit-scope.XXXXXX")"
    seen=""
    count=0
    while IFS= read -r raw || [ -n "$raw" ]; do
        # Trim surrounding whitespace and any CR from a Windows-authored manifest.
        path="$(printf '%s' "$raw" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
        [ -z "$path" ] && continue
        case "$path" in
            \#*) continue ;;
            /*)            die "unsafe exact-scope manifest path (absolute): $path" ;;
            *\\*)          die "unsafe exact-scope manifest path (backslash): $path" ;;
            ..|../*|*/../*|*/..) die "unsafe exact-scope manifest path (traversal): $path" ;;
        esac
        # Case-fold the duplicate check: on APFS and NTFS alike, `Docs/a.md` and
        # `docs/a.md` are one file, so accepting both would stage it twice and
        # make the manifest disagree with the tree it claims to describe.
        folded="$(printf '%s' "$path" | tr '[:upper:]' '[:lower:]')"
        if printf '%s\n' "$seen" | grep -Fxq "$folded"; then
            rm -f "$scope_file"
            die "duplicate exact-scope manifest path: $path"
        fi
        seen="$seen
$folded"
        if [ ! -f "$repo/$path" ]; then
            rm -f "$scope_file"
            die "exact-scope file is missing: $path"
        fi
        printf '%s\n' "$path" >> "$scope_file"
        count=$((count + 1))
    done < "$manifest"
    if [ "$count" -eq 0 ]; then
        rm -f "$scope_file"
        die "exact-scope manifest is empty"
    fi

    # Build the argv array once. bash 3.2 has no readarray, so read the file.
    local -a SCOPE
    SCOPE=()
    while IFS= read -r path; do
        SCOPE+=("$path")
    done < "$scope_file"

    # ---- Descriptor: every field present, and parent/tree/message all agree.
    local field descriptor_parent descriptor_tree descriptor_msg_sha
    local author_name author_email descriptor_fpr descriptor_timestamp
    for field in parent tree message_sha256 author_name author_email signing_fingerprint; do
        if [ -z "$(json_field "$descriptor" "$field")" ]; then
            rm -f "$scope_file"
            die "content descriptor is missing $field"
        fi
    done
    descriptor_parent="$(json_field "$descriptor" parent)"
    descriptor_tree="$(json_field "$descriptor" tree)"
    descriptor_msg_sha="$(json_field "$descriptor" message_sha256)"
    author_name="$(json_field "$descriptor" author_name)"
    author_email="$(json_field "$descriptor" author_email)"
    descriptor_fpr="$(json_field "$descriptor" signing_fingerprint)"
    descriptor_timestamp="$(json_field "$descriptor" timestamp)"

    if [ "$descriptor_parent" != "$EXPECTED_BASE" ] || [ "$descriptor_tree" != "$EXPECTED_TREE" ]; then
        rm -f "$scope_file"
        die "content descriptor parent/tree does not match approved values"
    fi
    local message_hash
    message_hash="$(sha256_file "$message_path")"
    if [ "$descriptor_msg_sha" != "$message_hash" ]; then
        rm -f "$scope_file"
        die "message file hash does not match content descriptor"
    fi

    # ---- Signing: enabled, ssh format, key on disk, fingerprint as approved.
    local signing_enabled signing_format signing_key
    signing_enabled="$(git_config_opt "$repo" commit.gpgsign)"
    signing_format="$(git_config_opt "$repo" gpg.format)"
    signing_key="$(git_config_opt "$repo" user.signingkey)"
    case "$signing_key" in "~"/*) signing_key="$HOME/${signing_key#~/}" ;; esac
    if [ "$signing_enabled" != "true" ] || [ "$signing_format" != "ssh" ] || [ ! -e "$signing_key" ]; then
        rm -f "$scope_file"
        die "exact-scope mode requires a usable local SSH commit-signing configuration
  commit.gpgsign=$signing_enabled gpg.format=$signing_format user.signingkey=$signing_key"
    fi
    local public_key
    if [ -e "$signing_key.pub" ]; then public_key="$signing_key.pub"; else public_key="$signing_key"; fi

    command -v ssh-keygen >/dev/null 2>&1 || { rm -f "$scope_file"; die_toolless "ssh-keygen not on PATH"; }
    local fingerprint
    fingerprint="$(ssh-keygen -lf "$public_key" -E sha256 2>/dev/null | tr ' ' '\n' | grep '^SHA256:' | head -n 1)" || true
    if [ -z "$fingerprint" ]; then
        rm -f "$scope_file"
        die "unable to derive SSH signing fingerprint from $public_key"
    fi
    if [ "$fingerprint" != "$descriptor_fpr" ]; then
        rm -f "$scope_file"
        die "SSH signing fingerprint does not match content descriptor
  key: $fingerprint
  approved: $descriptor_fpr"
    fi

    # verify-commit needs an allowed-signers file, so point it at this one key.
    local git_dir allowed_signers public_key_text
    git_dir="$(git_x "$repo" rev-parse --git-dir)"
    case "$git_dir" in /*) ;; *) git_dir="$repo/$git_dir" ;; esac
    allowed_signers="$git_dir/{{PROJECT_NAME}}-allowed-signers"
    public_key_text="$(head -n 1 "$public_key" | tr -d '\r' | sed -e 's/[[:space:]]*$//')"
    printf '%s %s\n' "$author_email" "$public_key_text" > "$allowed_signers"
    git_x "$repo" config gpg.ssh.allowedSignersFile "$allowed_signers" >/dev/null

    # ---- Stage into a throwaway index so the caller's index is untouched.
    local temp_index actual_sha actual_parent actual_tree tree
    temp_index="$(mktemp "${TMPDIR:-/tmp}/{{PROJECT_NAME}}-exact-index.XXXXXX")"
    # mktemp created an empty file; git read-tree wants to create it itself.
    rm -f "$temp_index"
    cleanup_exact() { rm -f "$temp_index" "$scope_file"; }
    trap cleanup_exact EXIT

    # These are exported and unset explicitly rather than written as a
    # `VAR=x git_x ...` prefix: a variable-assignment prefix on a *function* call
    # is temporary in default bash but persists in POSIX mode, and a stray
    # GIT_INDEX_FILE surviving into the caller's index operations is exactly the
    # kind of leak this mode exists to prevent.
    export GIT_INDEX_FILE="$temp_index"
    git_x "$repo" read-tree "$EXPECTED_BASE" >/dev/null
    git_x "$repo" add -- "${SCOPE[@]}" >/dev/null
    tree="$(git_x "$repo" write-tree)"
    if [ "$tree" != "$EXPECTED_TREE" ]; then
        die "exact-scope tree drift: expected $EXPECTED_TREE, got $tree"
    fi

    # Identity comes from the descriptor, not from whatever this shell inherited.
    export GIT_AUTHOR_NAME="$author_name" GIT_AUTHOR_EMAIL="$author_email"
    export GIT_COMMITTER_NAME="$author_name" GIT_COMMITTER_EMAIL="$author_email"
    if [ -n "$descriptor_timestamp" ]; then
        export GIT_AUTHOR_DATE="$descriptor_timestamp"
        export GIT_COMMITTER_DATE="$descriptor_timestamp"
    fi
    git_x "$repo" commit -S -F "$message_path" >/dev/null
    unset GIT_INDEX_FILE GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL \
          GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL
    unset GIT_AUTHOR_DATE GIT_COMMITTER_DATE 2>/dev/null || true

    actual_sha="$(git_x "$repo" rev-parse HEAD)"
    actual_parent="$(git_x "$repo" rev-parse 'HEAD^')"
    actual_tree="$(git_x "$repo" show -s --format=%T HEAD)"
    if [ "$actual_parent" != "$EXPECTED_BASE" ] || [ "$actual_tree" != "$EXPECTED_TREE" ]; then
        die "signed commit parent/tree does not match approved content"
    fi
    git_x "$repo" verify-commit "$actual_sha" >/dev/null

    # Bring only the committed scope entries in the caller's index to the new
    # HEAD. Any unrelated staged entries remain byte-for-byte staged.
    git_x "$repo" reset --quiet HEAD -- "${SCOPE[@]}" >/dev/null

    emit_state "$OUTPUT_STATE" "$actual_sha" "$actual_parent" "$actual_tree" \
               "$(sha256_file "$descriptor")" "$scope_file"

    trap - EXIT
    cleanup_exact
    printf 'Exact-scope signed commit verified: %s\n' "$actual_sha"
}

# --------------------------------------------------------------------------
# Selftest
# --------------------------------------------------------------------------
# This script stages, commits and pushes. It had no test at all, which is how the
# swallowed-exit-code defects in step 4 survived: nothing ever asserted that a refused
# gate *prevents the commit*, only that it printed something red. Every arm below runs
# the real CLI in a throwaway repository and then asks git whether a commit exists --
# the output is a claim, `git rev-list --count HEAD` is the fact.
#
# GIT_CONFIG_GLOBAL points at an empty file so the arms neither read nor honour the
# operator's real signing configuration; a suite that only passes on a machine with
# signing set up a particular way is a suite that fails on adopters' machines.
selftest() {
    local arms=0 fails=0 musts=0 tmp script bash_bin
    script="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    bash_bin="$(command -v bash)"
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/agent-commit-selftest-XXXXXX")" || {
        printf 'FAIL-CLOSED: no scratch directory, so nothing was tested.\n' >&2
        exit 3
    }
    printf '' >"$tmp/gitconfig"

    fresh_repo() {
        # $1 = repo dir. A real repository, because the assertions are git's.
        local r="$1"
        mkdir -p "$r"
        git -C "$r" init --quiet
        git -C "$r" config user.email "selftest@example.invalid"
        git -C "$r" config user.name "Selftest"
        git -C "$r" config commit.gpgsign false
        git -C "$r" config core.autocrlf false
        printf 'seed\n' >"$r/seed.txt"
        git -C "$r" add seed.txt
        git -C "$r" commit --quiet -m "seed"
    }

    commit_count() { git -C "$1" rev-list --count HEAD 2>/dev/null || printf '0\n'; }

    arm() {
        # arm LABEL EXPECT_EXIT MUST_SAY EXPECT_NEW_COMMITS REPO -- [SCRIPT_ARG...]
        #
        # EXPECT_NEW_COMMITS is the assertion the printed output cannot fake: 0 means the
        # tree must be untouched. A refusal that still commits is the defect this catches.
        local label="$1" want="$2" needle="$3" want_new="$4" repo="$5"; shift 5
        [ "${1-}" = "--" ] && shift
        local before after got out
        before="$(commit_count "$repo")"
        set +e
        out="$(cd "$repo" && env GIT_CONFIG_GLOBAL="$tmp/gitconfig" \
               "$bash_bin" "$script" "$@" 2>&1)"
        got=$?
        set -e
        after="$(commit_count "$repo")"
        arms=$((arms + 1))
        if [ "$want" = "0" ]; then musts=$((musts + 1)); fi
        if [ "$got" != "$want" ]; then
            printf 'FAIL %-36s want exit %s, got %s: %s\n' "$label" "$want" "$got" \
                "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-140)"
            fails=$((fails + 1)); return 0
        fi
        if [ -n "$needle" ] && case "$out" in *"$needle"*) false ;; *) true ;; esac; then
            printf 'FAIL %-36s exit %s but never said "%s": %s\n' "$label" "$got" "$needle" \
                "$(printf '%s' "$out" | tr '\n' ' ' | cut -c1-140)"
            fails=$((fails + 1)); return 0
        fi
        if [ "$((after - before))" != "$want_new" ]; then
            printf 'FAIL %-36s expected %s new commit(s), got %s (before=%s after=%s)\n' \
                "$label" "$want_new" "$((after - before))" "$before" "$after"
            fails=$((fails + 1)); return 0
        fi
        printf 'PASS %-36s exit %s, %s new commit(s)\n' "$label" "$got" "$((after - before))"
    }

    # -- run_gate: a refused gate must stop before step 5 --------------------
    fresh_repo "$tmp/r1"; printf 'change\n' >"$tmp/r1/work.txt"
    AGENT_COMMIT_TEST_CMD='exit 1' \
        arm "gate-refusal-prevents-commit" 1 "FAILED: AGENT_COMMIT_TEST_CMD (exit 1)" 0 "$tmp/r1" \
        -- --message "feat: should not land" --no-push

    # -- run_gate: 3 is preserved, not flattened into 1 ----------------------
    # The header promises "3 a required host tool is absent, so a check could not be
    # performed". run_gate used to exit 1 for every non-zero status, so the script
    # reported a refusal it had not obtained.
    fresh_repo "$tmp/r2"; printf 'change\n' >"$tmp/r2/work.txt"
    AGENT_COMMIT_TEST_CMD='exit 3' \
        arm "gate-unavailable-is-3-not-1" 3 "UNAVAILABLE: AGENT_COMMIT_TEST_CMD could not run (exit 3)" 0 "$tmp/r2" \
        -- --message "feat: should not land" --no-push

    fresh_repo "$tmp/r3"; printf 'change\n' >"$tmp/r3/work.txt"
    AGENT_COMMIT_TEST_CMD='no-such-tool-in-this-suite' \
        arm "gate-missing-tool-127-is-3" 3 "could not run (exit 127)" 0 "$tmp/r3" \
        -- --message "feat: should not land" --no-push

    # -- 4c: a crashed exporter must not report "up to date" -----------------
    # The exact reproduction from the independent review: uv exits non-zero, the diff is
    # therefore empty, and an empty diff used to be announced as the spec being current.
    fresh_repo "$tmp/r4"; printf 'change\n' >"$tmp/r4/work.txt"
    mkdir -p "$tmp/r4/tools" "$tmp/stubuv"
    printf 'print("stub")\n' >"$tmp/r4/tools/export_openapi.py"
    printf '#!/bin/sh\nexit 3\n' >"$tmp/stubuv/uv"; chmod +x "$tmp/stubuv/uv"
    PATH="$tmp/stubuv:$PATH" \
        arm "openapi-export-failure-refuses" 3 "spec drift is unknown" 0 "$tmp/r4" \
        -- --message "feat: should not land" --no-push

    # -- the positive paths --------------------------------------------------
    # Without these, a script that refused unconditionally would pass every arm above.
    fresh_repo "$tmp/r5"; printf 'change\n' >"$tmp/r5/work.txt"
    arm "clean-commit-lands" 0 "Committed successfully" 1 "$tmp/r5" \
        -- --message "feat: should land" --no-push --skip-tests

    fresh_repo "$tmp/r6"
    arm "nothing-to-commit-is-ok" 0 "Nothing to commit" 0 "$tmp/r6" \
        -- --message "feat: nothing here" --no-push --skip-tests

    # -- the attribution gate ------------------------------------------------
    fresh_repo "$tmp/r7"; printf 'change\n' >"$tmp/r7/work.txt"
    arm "ai-attribution-refused" 1 "must not include AI co-author" 0 "$tmp/r7" \
        -- --message "feat: x" --body "Co-Authored-By: Claude <noreply@anthropic.com>" --no-push --skip-tests

    # -- usage ---------------------------------------------------------------
    fresh_repo "$tmp/r8"
    arm "unknown-flag-is-usage" 2 "unknown argument" 0 "$tmp/r8" -- -Message "powershell style"
    arm "missing-message-is-usage" 2 "--message is required" 0 "$tmp/r8" -- --no-push

    rm -rf "$tmp"
    printf '\n'
    if [ "$fails" -gt 0 ]; then
        printf 'REFUSE: %d arm(s), %d failure(s)\n' "$arms" "$fails"
        return 1
    fi
    printf 'OK: %d arm(s), 0 failure(s) [%d must-pass arms, and every arm asserts the commit count, so a script that refused everything would fail]\n' \
        "$arms" "$musts"
    return 0
}

if [ "$SELFTEST" -eq 1 ]; then
    selftest
    exit $?
fi

if [ -n "$REPOSITORY_PATH$SCOPE_MANIFEST$EXPECTED_BASE$EXPECTED_TREE$CONTENT_DESCRIPTOR$MESSAGE_FILE$OUTPUT_STATE" ]; then
    exact_scope_commit
    exit 0
fi

# --------------------------------------------------------------------------
# Legacy commit mode
# --------------------------------------------------------------------------
[ -n "$MESSAGE" ] || usage_error "--message is required in legacy commit mode"

printf '\n%s=== Agent-Safe Git Commit ===%s\n' "$C_CYAN" "$C_RESET"

# A here-string, not a pipe: with `pipefail`, `printf ... | grep -q` can return
# grep's SIGPIPE-induced 141 on a *match*, which would read as "no match" and let
# the attribution through. The gate must not fail open.
if grep -Eiq \
    'co-authored-by:[[:space:]]*(claude|anthropic)|generated[[:space:]]+(with|by)[[:space:]]+(claude|anthropic)|authored[[:space:]]+(with|by)[[:space:]]+(claude|anthropic)' \
    <<< "$MESSAGE
$BODY"; then
    printf '%sERROR: Commit messages must not include AI co-author or generated-by attribution.%s\n' "$C_RED" "$C_RESET" >&2
    printf "%sRemove trailers such as 'Co-Authored-By: Claude' or 'Generated with Claude'.%s\n" "$C_RED" "$C_RESET" >&2
    exit 1
fi

# ---- Step 1: signing config -----------------------------------------------
printf '\n'
step "[1/7] Checking signing config..."
GPG_SIGN="$(git config --global commit.gpgsign 2>/dev/null || true)"
GPG_FORMAT="$(git config --global gpg.format 2>/dev/null || true)"
SIGNING_KEY="$(git config --global user.signingkey 2>/dev/null || true)"
case "$SIGNING_KEY" in "~"/*) SIGNING_KEY_PATH="$HOME/${SIGNING_KEY#~/}" ;; *) SIGNING_KEY_PATH="$SIGNING_KEY" ;; esac

if [ "$GPG_SIGN" = "true" ] && [ "$GPG_FORMAT" != "ssh" ]; then
    printf '%sERROR: GPG signing is enabled but format is %s (not ssh). This WILL hang.%s\n' \
        "$C_RED" "${GPG_FORMAT:-unset}" "$C_RESET" >&2
    printf '  git config --global gpg.format ssh\n' >&2
    printf '  git config --global user.signingkey "$HOME/.ssh/id_ed25519_signing.pub"\n' >&2
    exit 1
fi
if [ "$GPG_SIGN" = "true" ] && [ "$GPG_FORMAT" = "ssh" ]; then
    if [ -z "$SIGNING_KEY" ] || [ ! -e "$SIGNING_KEY_PATH" ]; then
        die "SSH signing key not found at '$SIGNING_KEY'."
    fi
    ok "SSH signing: OK (key: $SIGNING_KEY)"
else
    warn "Signing: disabled (commits will be unsigned)"
fi

# ---- Step 2: remote URL ---------------------------------------------------
step "[2/7] Checking remote URL..."
REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
case "$REMOTE_URL" in
    https://*)
        # GIT_TERMINAL_PROMPT=0 is exported above, so this fails fast instead of
        # hanging -- but it still fails, so say so before the work happens.
        warn "WARNING: remote uses HTTPS ($REMOTE_URL) — push will fail rather than prompt." ;;
    "") warn "WARNING: no 'origin' remote configured." ;;
    *)  ok "Remote: OK ($REMOTE_URL)" ;;
esac

# ---- Step 3: stage --------------------------------------------------------
step "[3/7] Staging changes..."
git add -A
STATUS="$(git status --short)"
if [ -z "$STATUS" ]; then
    warn "Nothing to commit — working tree clean."
    exit 0
fi
FILE_COUNT="$(grep -c '' <<< "$STATUS" || true)"
ok "Staged $FILE_COUNT file(s)"

# ---- Step 4: lint + tests -------------------------------------------------
# Portability note: the PowerShell script hardcodes this project's gates
# (`uv run ruff check packages/ tests/`, `uv run pytest tests/unit/`). Hardcoding
# them here would make the script hard-fail in any repo laid out differently, so
# each gate is guarded on its tooling being present -- and a guard that trips
# prints SKIPPED, never "passed". A gate that reports success because its tool
# was missing is worse than no gate. Override the whole step with
# AGENT_COMMIT_TEST_CMD to run your own command instead.
run_gate() {
    # $1 = label, rest = command
    #
    # The status is propagated, not translated. This used to `exit 1` for every non-zero
    # status, which quietly contradicted the header's own contract: a gate whose *tool* is
    # missing exits 127 (or, for the tools in this package, 3), and reporting that as "the
    # gate refused" is how a repo comes to believe an unrun check said no. 1 and 3 are
    # different facts here for the same reason they are everywhere else in this package.
    local label="$1"; shift
    local out status
    set +e
    out="$("$@" 2>&1)"
    status=$?
    set -e
    if [ "$status" -eq 0 ]; then
        ok "$label: passed"
        return 0
    fi
    if [ "$status" -eq 3 ] || [ "$status" -eq 127 ]; then
        printf '  %sUNAVAILABLE: %s could not run (exit %s)%s\n' "$C_RED" "$label" "$status" "$C_RESET" >&2
        printf '%s\n' "$out" >&2
        exit 3
    fi
    printf '  %sFAILED: %s (exit %s)%s\n' "$C_RED" "$label" "$status" "$C_RESET" >&2
    printf '%s\n' "$out" >&2
    exit 1
}

if [ "$SKIP_TESTS" -eq 1 ]; then
    warn "[4/7] Lint + tests skipped (--skip-tests)"
elif [ -n "${AGENT_COMMIT_TEST_CMD-}" ]; then
    step "[4/7] Running AGENT_COMMIT_TEST_CMD..."
    run_gate "AGENT_COMMIT_TEST_CMD" sh -c "$AGENT_COMMIT_TEST_CMD"
else
    step "[4/7] Running lint + tests..."

    # 4a: lint
    if command -v uv >/dev/null 2>&1 && [ -d packages ] && [ -d tests ]; then
        run_gate "Ruff" uv run ruff check packages/ tests/
    else
        warn "[4a] SKIPPED lint: need 'uv' on PATH plus packages/ and tests/ (set AGENT_COMMIT_TEST_CMD)"
    fi

    # 4b: unit tests
    if command -v uv >/dev/null 2>&1 && [ -d tests/unit ]; then
        run_gate "Unit tests" uv run pytest tests/unit/ -x --tb=line -q
    else
        warn "[4b] SKIPPED unit tests: need 'uv' on PATH plus tests/unit/ (set AGENT_COMMIT_TEST_CMD)"
    fi

    # 4c: OpenAPI spec drift — regenerate and stage rather than fail.
    #
    # "Regenerate rather than fail" applies to *drift*, not to the regeneration itself.
    # Both statuses used to be discarded (`|| true`, `2>/dev/null || true`), so an exporter
    # that crashed produced no diff, and no diff was reported as "up to date" — the check
    # announced the strongest possible result precisely when it had learned nothing. If the
    # exporter or the diff cannot run, that is exit 3; if the exporter refuses, that is 1.
    if command -v uv >/dev/null 2>&1 && [ -f tools/export_openapi.py ]; then
        set +e
        export_out="$(uv run python tools/export_openapi.py -o openapi.committed.json 2>&1)"
        export_status=$?
        set -e
        if [ "$export_status" -ne 0 ]; then
            printf '  %sFAILED: OpenAPI export exited %s, so spec drift is unknown%s\n' \
                "$C_RED" "$export_status" "$C_RESET" >&2
            printf '%s\n' "$export_out" >&2
            if [ "$export_status" -eq 3 ] || [ "$export_status" -eq 127 ]; then
                exit 3
            fi
            exit 1
        fi
        set +e
        spec_diff="$(git diff --name-only openapi.committed.json 2>&1)"
        diff_status=$?
        set -e
        if [ "$diff_status" -ne 0 ]; then
            printf '  %sFAILED: git diff on openapi.committed.json exited %s, so drift is unknown%s\n' \
                "$C_RED" "$diff_status" "$C_RESET" >&2
            printf '%s\n' "$spec_diff" >&2
            exit 1
        fi
        if [ -n "$spec_diff" ]; then
            warn "OpenAPI spec was stale — auto-regenerated and staged."
            git add openapi.committed.json
        else
            ok "OpenAPI spec: up to date"
        fi
    else
        warn "[4c] SKIPPED OpenAPI drift check: tools/export_openapi.py not present"
    fi
fi

# ---- Step 5: commit -------------------------------------------------------
step "[5/7] Committing..."
if [ -n "$BODY" ]; then
    git commit -m "$MESSAGE" -m "$BODY" || die "git commit failed with exit code $?"
else
    git commit -m "$MESSAGE" || die "git commit failed with exit code $?"
fi
ok "Committed successfully"

# ---- Step 6: push ---------------------------------------------------------
if [ "$NO_PUSH" -eq 0 ]; then
    step "[6/7] Pushing to origin/$BRANCH..."
    git push origin "$BRANCH" || die "git push failed with exit code $?"
    ok "Pushed successfully"
else
    warn "[6/7] Push skipped (--no-push)"
fi

# ---- Step 7: verify -------------------------------------------------------
step "[7/7] Verifying..."
ok "Latest: $(git log --oneline -1)"
printf '\n%s=== Done ===%s\n' "$C_CYAN" "$C_RESET"
