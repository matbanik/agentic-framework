# Messaging probe kit

This kit tests whether an orchestrator can send messages into a running headless `claude -p`.
It uses file inbox hooks (PostToolUse and Stop) and a blocking wait helper.
`run_gate.py` is the M-1 gate. It exits 0 only when every requested case passed.

The kit is portable. All code resolves from the directory that holds the kit.
The kit never writes there. All output goes to the `--out` directory.

## Run the offline self-test

This does not call `claude`. It costs nothing.

```
python run_gate.py --self-test --out <scratch dir>
```

It renders the hook settings, checks the hook commands point into the kit and are quoted,
runs `inbox_hook.py` and `wait_msg.py` directly, and checks the kit was not modified.

## Run the live gate

Live cases call `claude` with the cheapest model alias (`kit.py`) on your subscription. They cost money.

```
python run_gate.py --out <scratch dir> --project <project dir> [--python <exe>] [--claude <exe>] [--cases T1,T2,T6c,T7,T9]
```

Default cases: T1, T2, T6c, T7, T9. Known ids: T1 T2 T3 T4 T5 T6b T6c T7 T8 T9.
The id-to-function map is in the `run_gate.py` docstring.

`gate-result.json` holds `cli_version` and `qualifying`. `qualifying` is true only for a live
run of the full default set in which every case passed. A self-test, a `--cases` subset or a
failed case writes false, and so does a run whose `claude --version` did not exit 0 with a parsed
`MAJOR.MINOR.PATCH`.

Before the scheduler uses a receipt, it runs:

```
python run_gate.py --check-receipt <gate-result.json> --project <project dir> --python <hook exe> [--claude <exe>]
```

Exit 0 only when the receipt is qualifying and live, every default case passed, its
`cli_version` equals the installed CLI version, and its project and `kit_revision` equal the
current ones. It also checks the **launch profile** (round-5 finding 4): the hook interpreter
and its version, and a digest of the hook keys of each settings file that the CLI merges for the
project (user, project, project-local and, on Windows, managed). The hook keys are every key whose
name contains `hook` (`hooks`, `disableAllHooks`, `allowManagedHooksOnly`, `allowedHttpHookUrls`,
`httpHookAllowedEnvVars` and any later one, so a new hook-policy key fails closed) plus `env`,
`enabledPlugins` and `disableCommandPluginSources` (round-6 finding 3). Each must equal what the receipt recorded. `--python` (or `MSG_PROBE_PYTHON`) is
required here and has no default; the scheduler passes `launch.python_exe`. Any kit edit changes
`kit_revision`, and any interpreter or hook-settings change changes the profile, so either needs a
new live run (report section 10.2, M-1).

## Options

| Option | Env var | Default |
|---|---|---|
| `--out` | `MSG_PROBE_OUT` | none; required |
| `--project` | `MSG_PROBE_PROJECT` | current directory |
| `--python` | `MSG_PROBE_PYTHON` | `sys.executable` (none for `--check-receipt`: required) |
| `--claude` | `MSG_PROBE_CLAUDE` | `claude` on PATH |

## Exit codes

- `0`: every requested case passed (or every self-test check passed).
- `1`: at least one case or check failed.
- `2`: usage or config error (missing `claude`, bad interpreter, `--out` not writable or inside the kit, unknown case id).

## Output

`gate-result.json` in `--out` holds the identity and the per-case results.
Identity: `claude --version` (live runs only), sha256 of every kit `.py` file and every rendered
settings file, interpreter path and version, and the project path.
Each case has a boolean `passed`. An exception counts as `passed: false` with the error recorded.

Each probe script (`probe.py`, `probe2.py`, `probe3.py`, `probe3b.py`, `probe3c.py`, `probe4.py`)
also runs alone with the same four options. It exits 1 if any of its cases failed.
