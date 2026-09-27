# Concurrent Verus Database - SkySynth on Windows

This example asks Codex and SkySynth to synthesize an executable concurrent
database together with a Verus proof of the fixed atomic contract. Correctness
is the only objective; there is no performance benchmark yet.

The immutable [evaluator/mod.rs](evaluator/mod.rs) is the user-supplied
concurrent specification. It is intentionally an **atomic-contract** design,
not a `tokenized_state_machine!` design:

- `DatabaseState` is a tracked abstract `Map<Seq<char>, i32>`;
- one `GhostVar` location links that abstract map to one database instance;
- `impl_db!` gives `get`, `put`, `scan`, and `sort` atomic contracts;
- the candidate must consume each `*_lp` proof object at the executable
  linearization point and prove the concrete representation agrees with the
  abstract map there.

Passing this task therefore proves operation-level safety and linearizability
against the abstract map. It does not prove progress properties such as deadlock
freedom or starvation freedom.

## One-time Windows setup

```powershell
$env:VERUS = 'C:\path\to\verus\verus.exe'
$env:VERUS_Z3_PATH = 'C:\path\to\verus\z3.exe'
$env:SKYDISCOVER_BASH = 'C:\Program Files\Git\bin\bash.exe'

Set-Location C:\path\to\skydiscover
python -m skydiscover.main init --agent codex --path .
```

For an interactive desktop run, restart or create a Codex task after `init` so
the task reloads the local SkySynth skill and agent roles. The automated loop
below does not require opening a new desktop task for every iteration.

## Run the automated proof loop

One PowerShell command runs up to 20 complete iterations. Each iteration starts
two separate, sequential `codex exec` sessions:

```text
latest Verus result + current plan + candidate
    -> Planner edits synthesis/plan.md
    -> Coding Agent reads that plan and edits candidate/implementation.rs
    -> controller runs Verus --no-cheating
    -> next iteration receives the new error log
```

The Planner's fixed role prompt is [planner_prompt.md](planner_prompt.md); the
Coding Agent's fixed role prompt is [prompt.md](prompt.md). The controller freezes
both prompts, the task, the formal interface, and the client test in a hashed run
contract. Both role prompts are self-contained because the agents run in narrow
work directories and cannot read the repository's installed skill files there.
The controller keeps the latest candidate even when a proof attempt regresses, so
the next Planner can inspect and repair that exact attempt. The strongest
verified candidate and strongest partial proof are reported separately.

```powershell
Set-Location D:\论文\workspace\skydiscover
.\skydiscover\synthesize\examples\verus-db-windows\run_windows.ps1 `
    -Iterations 20 `
    -Verus 'D:\论文\tools\verus\dist\verus-x86-win\verus.exe' `
    -Z3 'D:\论文\tools\verus\dist\verus-x86-win\z3.exe'
```

The default run directory is `.skydiscover/verus-db-windows-planned`. Repeating
the command resumes at the next completed iteration; it never overwrites a
completed iteration. Success stops the run early. Add `-KeepGoing` to force all
20 iterations even after a verified candidate. Use `-DryRun` to save the next
Planner/Coding Agent prompts under `preview/` without consuming an iteration.
Use `-VerifyOnly` to check the current candidate. The CLI must be signed in once
in the dedicated `CodexHome` (which the PowerShell script selects by default).

Each completed `iterations/NNN/` directory contains `plan.before.md`,
`plan.after.md`, `plan.diff`, `implementation.before.rs`,
`implementation.after.rs`, `implementation.diff`, both complete agent prompts,
both agents' JSONL transcripts and stderr logs, Verus stdout/stderr,
`verification.json`, and `metadata.json` with hashes. The latest editable plan
is `synthesis/plan.md`; the latest candidate is `candidate/implementation.rs`.
An interrupted agent attempt goes under `interruptions/` with its available logs.
On restart, the controller restores that attempt's starting plan and code and
retries the same iteration number.

Both Codex sessions use `--approve-for-me`, which routes routine approval
requests through automatic review in the workspace sandbox. The Planner runs in
the plan directory and the Coding Agent in the candidate directory; the
controller rejects unexpected files or cross-role edits. Authentication failure
or an agent command failure stops the run and preserves the attempt for review.
No API key or performance benchmark is required.

## Run interactively instead

From a Codex task opened at the SkyDiscover repository root, enter:

```text
Read skydiscover/synthesize/examples/verus-db-windows/prompt.md and carry out its
instructions for the fixed task in
skydiscover/synthesize/examples/verus-db-windows/task.md.
```

SkySynth copies the fixed evaluator into a run directory and iterates through:

```text
Planner -> DSA proof attempts -> Verus feedback -> ISA on repeated stalls
        -> Auditor -> independent final proof check
```

The candidate must provide `VerifiedDb`, `id()`, the tracked-state constructor,
and an `impl_db!` invocation containing the four executable method bodies.

## What the evaluator enforces

- the exact concurrent contract is pinned by SHA-256;
- the constructor-shape test is also pinned;
- common Verus proof escape hatches, unsafe code, source inclusion and custom
  macros are rejected;
- the candidate must instantiate the fixed `impl_db!` macro;
- Verus runs with `--no-cheating` over the entire staged crate;
- the verified crate must compile and its executable must start successfully.

The old file under `candidates/baseline/` is a sequential historical fixture. It
is used only as editable starting text; the checker rejects it as a completed
solution to this concurrent contract.

## Files

| Path | Purpose |
|---|---|
| `task.md` | Concurrent synthesis and proof goal read by SkySynth |
| `prompt.md` | Exact English prompt read by the automated controller |
| `planner_prompt.md` | Fixed English Planner role prompt |
| `evaluator/mod.rs` | Immutable atomic contract supplied by the user |
| `evaluator/tests/database_test.rs` | Requires a constructible `VerifiedDb` and initial tracked state |
| `evaluator/tests/proof.py` | Adapter from the SkySynth suite to the Windows verifier |
| `verify_candidate.py` | Pinned, fail-closed Verus checker |
| `run_windows.ps1` | Windows entry point for repeated `codex exec` iterations |
| `run_windows.py` | Planner/Coding Agent loop, per-iteration snapshots, and independent checking |
| `candidates/baseline/` | Historical sequential fixture only |
