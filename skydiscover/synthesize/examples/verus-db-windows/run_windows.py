"""Run a Windows-native Codex/Verus repair loop for the database example."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from verify_candidate import (
    DEFAULT_INTERFACE, DEFAULT_TEST, check_candidate, lf_bytes,
    resolve_executable, verify,
)


HERE = Path(__file__).resolve().parent
DEFAULT_SEED = HERE / "candidates" / "baseline" / "implementation.rs"
DEFAULT_TASK = HERE / "task.md"
DEFAULT_PROMPT = HERE / "prompt.md"
DEFAULT_PLANNER_PROMPT = HERE / "planner_prompt.md"
DEFAULT_RUN_DIR = HERE.parents[3] / ".skydiscover" / "verus-db-windows-planned"
INITIAL_PLAN = """# Proof plan

## Workload
Awaiting the Planner's first assessment.

## Candidates
Awaiting the Planner's first assessment.

## Brief
Awaiting the Planner's first assessment.

## Learnings
No completed attempts yet.
"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_lf(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data.replace(b"\r\n", b"\n"))


def source_lines(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def completed_iterations(run_dir: Path) -> int:
    iterations = run_dir / "iterations"
    if not iterations.is_dir():
        return 0
    completed = 0
    for path in sorted(iterations.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or not path.name.isdigit() or int(path.name) <= 0:
            continue
        verification_path = path / "verification.json"
        if not verification_path.is_file():
            break
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        if int(path.name) != completed + 1:
            break
        if ((verification.get("planner_returncode", 0) != 0
                or verification.get("codex_returncode") != 0)
                and not verification.get("controller_fallback", False)):
            break
        completed = int(path.name)
    return completed


def resolve_command(value: str) -> str:
    found = shutil.which(value)
    if found:
        return found
    path = Path(value).expanduser().resolve()
    if path.is_file():
        return str(path)
    raise ValueError(f"command not found: {value}")


def load_manifest(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "contract" / "manifest.json"
    if not path.is_file():
        raise ValueError(f"run contract manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for relative, expected in manifest["sha256"].items():
        actual = digest((run_dir / "contract" / relative).read_bytes())
        if actual != expected:
            raise ValueError(f"frozen contract was modified: {relative}")
    return manifest


def initialize_run(
    run_dir: Path,
    seed: Path,
    prompt: Path,
    fresh: bool,
    planner_prompt: Path = DEFAULT_PLANNER_PROMPT,
) -> None:
    if fresh and run_dir.exists():
        allowed_parent = (HERE.parents[3] / ".skydiscover").resolve()
        if not run_dir.resolve().is_relative_to(allowed_parent) or run_dir.resolve() == allowed_parent:
            raise ValueError("--fresh may remove only a named run inside the repository .skydiscover directory")
        marker = run_dir / "contract" / "manifest.json"
        if not marker.is_file():
            raise ValueError("refusing to remove an unmarked directory; choose a new --run-dir")
        load_manifest(run_dir)
        shutil.rmtree(run_dir)
    contract = run_dir / "contract"
    candidate = run_dir / "candidate"
    if (contract / "manifest.json").is_file():
        manifest = load_manifest(run_dir)
        if "planner_prompt.md" not in manifest["sha256"]:
            raise ValueError("existing run has no Planner contract; choose a new --run-dir")
        if not (candidate / "implementation.rs").is_file():
            raise ValueError("existing run has no candidate/implementation.rs")
        if not (run_dir / "synthesis" / "plan.md").is_file():
            raise ValueError("existing run has no synthesis/plan.md")
        return

    if run_dir.exists() and any(run_dir.iterdir()):
        raise ValueError("run directory is non-empty but has no valid manifest; use --fresh")

    files = {
        "interface/mod.rs": lf_bytes(DEFAULT_INTERFACE),
        "tests/database_test.rs": lf_bytes(DEFAULT_TEST),
        "task.md": lf_bytes(DEFAULT_TASK),
        "prompt.md": lf_bytes(prompt.resolve()),
        "planner_prompt.md": lf_bytes(planner_prompt.resolve()),
    }
    for relative, data in files.items():
        write_lf(contract / relative, data)
    manifest = {
        "format": 1,
        "created_by": "SkyDiscover Windows Verus loop",
        "sha256": {name: digest(data) for name, data in files.items()},
    }
    (contract / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_lf(candidate / "implementation.rs", lf_bytes(seed.resolve()))
    write_lf(run_dir / "synthesis" / "plan.md", INITIAL_PLAN.encode("utf-8"))


def save_iteration(
    run_dir: Path,
    number: int,
    result: dict[str, Any],
    *,
    prompt: str | None = None,
    stdout: str = "",
    stderr: str = "",
    artifacts: dict[str, str | bytes] | None = None,
) -> Path:
    folder = run_dir / "iterations" / f"{number:03d}"
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copy2(run_dir / "candidate" / "implementation.rs", folder / "implementation.rs")
    (folder / "verification.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if prompt is not None:
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
        (folder / "codex.stdout.log").write_text(stdout, encoding="utf-8", newline="\n")
        (folder / "codex.stderr.log").write_text(stderr, encoding="utf-8", newline="\n")
    for name, value in (artifacts or {}).items():
        destination = folder / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            destination.write_bytes(value)
        else:
            destination.write_text(value, encoding="utf-8", newline="\n")
    return folder


def unified_diff(before: bytes, after: bytes, name: str) -> str:
    return "".join(difflib.unified_diff(
        before.decode("utf-8", errors="replace").splitlines(keepends=True),
        after.decode("utf-8", errors="replace").splitlines(keepends=True),
        fromfile=f"{name}.before", tofile=f"{name}.after",
    ))


def concise_feedback(result: dict[str, Any], limit: int | None = 12000) -> str:
    if result.get("success"):
        summary = result.get("summary") or {}
        return (
            f"The current candidate passed: verified={summary.get('verified')}, "
            f"errors={summary.get('errors')}. Preserve the implementation and proof unless "
            "a change is required to satisfy the fixed formal specification."
        )
    combined = "\n".join(
        str(result.get(name, "")) for name in ("reason", "stdout", "stderr")
    ).strip()
    if limit is not None:
        combined = combined[-limit:]
    return combined or "The candidate did not pass the independent verifier."


def recent_attempt_history(run_dir: Path, iteration: int, limit: int = 3) -> str:
    records: list[str] = []
    first = max(1, iteration - limit)
    for number in range(first, iteration):
        folder = run_dir / "iterations" / f"{number:03d}"
        verification_path = folder / "verification.json"
        candidate_path = folder / "implementation.rs"
        if not verification_path.is_file() or not candidate_path.is_file():
            continue
        verification = json.loads(verification_path.read_text(encoding="utf-8"))
        agent_path = folder / "coder.stdout.jsonl"
        if not agent_path.is_file():
            agent_path = folder / "codex.stdout.log"
        agent_summary = agent_final_message(agent_path)
        plan_change_path = folder / "plan.diff"
        plan_change = (
            plan_change_path.read_text(encoding="utf-8", errors="replace")[-2500:].strip()
            if plan_change_path.is_file()
            else "No plan difference was captured."
        )
        records.append(
            f"""Iteration {number}
candidate_sha256: {digest(candidate_path.read_bytes())}
plan change:
{plan_change}
agent report:
{agent_summary}
independent verifier:
{concise_feedback(verification, limit=4000)}"""
        )
    return "\n\n".join(records) or "No earlier completed attempt is available."


def agent_final_message(path: Path) -> str:
    if not path.is_file():
        return "No agent summary was captured."
    contents = path.read_text(encoding="utf-8", errors="replace")
    for line in reversed(contents.splitlines()):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            return str(item["text"])[-3000:]
    return contents[-3000:].strip() or "No agent summary was captured."


def pinned_toolchain_context(verus_path: Path, z3_path: Path) -> str:
    """Describe the exact local Verus/vstd sources available to the agents."""
    toolchain_root = verus_path.parent.resolve()
    vstd_root = toolchain_root / "vstd"
    atomic_source = vstd_root / "atomic.rs"
    return f"""PINNED VERUS TOOLCHAIN (READ-ONLY)
---------------------------------
Use the exact local toolchain below; do not infer APIs from memory or from a
different Verus checkout.

Verus executable:
{verus_path.resolve()}
Z3 executable:
{z3_path.resolve()}
Pinned vstd source root:
{vstd_root}
Pinned atomic source:
{atomic_source}

Before changing atomic-with-ghost or token-state-machine code, inspect these
files directly. The Windows agent environment may not provide `rg`. Use the
following PowerShell commands instead:

Get-Content -Raw '{atomic_source}'
Select-String -Path '{atomic_source}' -Pattern 'open_atomic|au_commit|Commit'
Get-ChildItem -Path '{vstd_root}' -Recurse -Filter '*.rs' | Select-String -Pattern 'open_atomic|au_commit|Commit'

Do not guess a macro, helper, field, or module name when the pinned source can
settle it. Treat this toolchain context as read-only evidence.
"""


def build_planner_prompt(
    run_dir: Path,
    iteration: int,
    result: dict[str, Any],
    toolchain: str = "",
) -> str:
    contract = run_dir / "contract"
    base_prompt = (contract / "planner_prompt.md").read_text(encoding="utf-8").rstrip()
    task = (contract / "task.md").read_text(encoding="utf-8")
    interface = (contract / "interface" / "mod.rs").read_text(encoding="utf-8")
    test = (contract / "tests" / "database_test.rs").read_text(encoding="utf-8")
    plan = (run_dir / "synthesis" / "plan.md").read_text(encoding="utf-8")
    candidate = (run_dir / "candidate" / "implementation.rs").read_text(encoding="utf-8")
    return f"""{base_prompt}

AUTOMATED PLANNER ITERATION {iteration}
---------------------------------
Update plan.md in the current directory. It is your only writable artifact.
The Coding Agent will receive your updated plan in a separate session.

{toolchain}

IMMUTABLE TASK
--------------
{task}

IMMUTABLE INTERFACE
-------------------
```rust
{interface}
```

IMMUTABLE CLIENT TEST
---------------------
```rust
{test}
```

CURRENT PLAN
------------
{plan}

CURRENT CANDIDATE (read-only evidence)
--------------------------------------
```rust
{candidate}
```

LATEST INDEPENDENT VERUS RESULT
-------------------------------
{concise_feedback(result, limit=None)}

RECENT COMPLETED ATTEMPTS
-------------------------
{recent_attempt_history(run_dir, iteration)}
"""


def build_prompt(
    run_dir: Path,
    iteration: int,
    result: dict[str, Any],
    toolchain: str = "",
) -> str:
    contract = run_dir / "contract"
    base_prompt = (contract / "prompt.md").read_text(encoding="utf-8").rstrip()
    task = (contract / "task.md").read_text(encoding="utf-8")
    interface = (contract / "interface" / "mod.rs").read_text(encoding="utf-8")
    test = (contract / "tests" / "database_test.rs").read_text(encoding="utf-8")
    plan = (run_dir / "synthesis" / "plan.md").read_text(encoding="utf-8")
    return f"""{base_prompt}

AUTOMATED ITERATION CONTEXT
---------------------------
You are iteration {iteration} of a Windows Codex/Verus proof-repair loop.
You are the Coding Agent. A separate Planner has just updated plan.md. Follow its
one bounded brief and use the verifier evidence to implement that step.

{toolchain}

Edit ONLY implementation.rs in the current directory. Do not create or edit any
contract, verifier, configuration, or test file. Do not use assume, admit,
external_body, unsafe, source inclusion, or other proof escape hatches. The
controller will independently run Verus with --no-cheating after you finish.

Your only objective is proof correctness. Implement the executable database and its
proof so that every requires/ensures clause in the immutable interface is satisfied,
the entire crate verifies with zero errors under Verus --no-cheating, and the verified
client compiles and runs successfully.

Do not optimize runtime performance, source-code size, proof length, or style. Do not
weaken, replace, or reinterpret the specification. If the current candidate already
passes completely, leave it unchanged. Otherwise, use the verifier feedback to repair
implementation.rs. Do not merely describe a patch: edit implementation.rs itself.

TASK
----
{task}

IMMUTABLE INTERFACE
-------------------
```rust
{interface}
```

IMMUTABLE CLIENT TEST
---------------------
```rust
{test}
```

PLANNER PLAN (read-only; do not modify it)
---------------------------------------
{plan}

PREVIOUS INDEPENDENT VERIFIER RESULT
------------------------------------
{concise_feedback(result)}

RECENT FAILED ATTEMPTS
----------------------
{recent_attempt_history(run_dir, iteration)}

Do not repeat or revert to a candidate hash shown above when it produced the same
proof obligation. Make one concrete code/proof change from the Planner's brief;
the controller will independently verify it after this session.
"""


def run_codex(
    codex: str,
    working_dir: Path,
    prompt: str,
    *,
    model: str | None,
    reasoning_effort: str | None,
    timeout: int,
    environment: dict[str, str],
) -> tuple[int, str, str]:
    command = [
        codex,
        "exec",
        "--skip-git-repo-check",
        "--color",
        "never",
        "--json",
        "--ephemeral",
        # The current Codex CLI uses this supported non-interactive flag.
        # The older --approve-for-me flag makes `codex exec` exit immediately.
        "--dangerously-bypass-approvals-and-sandbox",
        "--cd",
        str(working_dir),
    ]
    if model:
        command.extend(["--model", model])
    if reasoning_effort:
        command.extend(["-c", f"model_reasoning_effort={reasoning_effort}"])
    command.append("-")
    try:
        process = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=environment,
        )
        return process.returncode, process.stdout, process.stderr
    except subprocess.TimeoutExpired as error:
        def as_text(value: str | bytes | None) -> str:
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        return 124, as_text(error.stdout), as_text(error.stderr) + f"\nTimed out after {timeout}s"


def validate_agent_workspace(directory: Path, allowed: str) -> None:
    files = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
    if files != {allowed}:
        raise ValueError(f"agent workspace contains unexpected files: {directory}: {sorted(files)}")


def archive_interrupted_round(run_dir: Path) -> Path | None:
    partial = run_dir / "in_progress"
    if not partial.exists():
        return None
    plan_before = partial / "plan.before.md"
    code_before = partial / "implementation.before.rs"
    if plan_before.is_file():
        (run_dir / "synthesis" / "plan.md").write_bytes(plan_before.read_bytes())
    if code_before.is_file():
        (run_dir / "candidate" / "implementation.rs").write_bytes(code_before.read_bytes())
    archive = run_dir / "interruptions" / f"attempt-{time.time_ns()}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial.rename(archive)
    return archive


def write_round_file(folder: Path, name: str, data: str | bytes) -> None:
    destination = folder / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        destination.write_bytes(data)
    else:
        destination.write_text(data, encoding="utf-8", newline="\n")


def check_codex_login(codex: str, environment: dict[str, str]) -> None:
    status = subprocess.run(
        [codex, "login", "status"],
        capture_output=True,
        text=True,
        errors="replace",
        env=environment,
    )
    message = (status.stdout + status.stderr).strip()
    if status.returncode != 0 or "not logged in" in message.lower():
        raise ValueError("Codex CLI is not logged in. Run `codex login` once, then retry.")


def is_better(result: dict[str, Any], lines: int, best: dict[str, Any] | None) -> bool:
    if not result.get("success"):
        return False
    if best is None:
        return True
    return lines < int(best["nonempty_lines"])


def proof_progress(result: dict[str, Any]) -> tuple[int, int, int]:
    """Order candidates by checker evidence, never by an agent's own claim."""
    summary = result.get("summary") or {}
    verified = int(summary.get("verified") or 0)
    errors = int(summary.get("errors") or 0)
    if result.get("success"):
        return (3, verified, -errors)
    if result.get("stage") == "verify":
        return (2, verified, -errors)
    return (1, 0, 0)


def best_progress_snapshot(
    run_dir: Path,
    current_result: dict[str, Any],
    current_candidate: bytes,
) -> tuple[dict[str, Any], bytes, int]:
    best_result = current_result
    best_candidate = current_candidate
    best_iteration = completed_iterations(run_dir)
    iterations = run_dir / "iterations"
    if not iterations.is_dir():
        return best_result, best_candidate, best_iteration
    for folder in sorted(iterations.iterdir(), key=lambda item: item.name):
        verification_path = folder / "verification.json"
        candidate_path = folder / "implementation.rs"
        if not folder.is_dir() or not verification_path.is_file() or not candidate_path.is_file():
            continue
        candidate_result = json.loads(verification_path.read_text(encoding="utf-8"))
        if folder.name != "000" and candidate_result.get("codex_returncode") != 0:
            continue
        if proof_progress(candidate_result) > proof_progress(best_result):
            best_result = candidate_result
            best_candidate = candidate_path.read_bytes()
            best_iteration = int(folder.name)
    return best_result, best_candidate, best_iteration


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    command.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    command.add_argument("--prompt", type=Path, default=DEFAULT_PROMPT)
    command.add_argument("--planner-prompt", type=Path, default=DEFAULT_PLANNER_PROMPT)
    command.add_argument("--iterations", type=int, default=20)
    command.add_argument("--verus")
    command.add_argument("--z3")
    command.add_argument("--codex", default="codex")
    command.add_argument("--codex-home", type=Path)
    command.add_argument("--model", default="gpt-5.6-sol")
    command.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh", "max", "ultra"),
        default=None,
        help="Optional Codex reasoning effort; omit to use the CLI default.",
    )
    command.add_argument(
        "--planner-retries",
        type=int,
        default=1,
        help="Planner attempts per iteration (default: 1; no retry).",
    )
    command.add_argument(
        "--coder-retries",
        type=int,
        default=1,
        help="Coding Agent attempts per iteration (default: 1; no retry).",
    )
    command.add_argument("--verification-timeout", type=int, default=240)
    command.add_argument("--agent-timeout", type=int, default=3600)
    command.add_argument("--fresh", action="store_true")
    command.add_argument("--keep-going", action="store_true")
    command.add_argument("--keep-regressions", action="store_true")
    command.add_argument("--verify-only", action="store_true")
    command.add_argument("--dry-run", action="store_true")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.iterations < 0:
        print("--iterations must be non-negative", file=sys.stderr)
        return 2
    if args.planner_retries < 1:
        print("--planner-retries must be at least 1", file=sys.stderr)
        return 2
    if args.coder_retries < 1:
        print("--coder-retries must be at least 1", file=sys.stderr)
        return 2
    run_dir = args.run_dir.resolve()
    try:
        initialize_run(run_dir, args.seed, args.prompt, args.fresh, args.planner_prompt)
        recovered = archive_interrupted_round(run_dir)
        if recovered:
            print(f"Archived interrupted attempt and restored its starting files: {recovered}")
        manifest = load_manifest(run_dir)
        candidate = run_dir / "candidate"
        plan_dir = run_dir / "synthesis"
        plan_path = plan_dir / "plan.md"
        candidate_path = candidate / "implementation.rs"
        validate_agent_workspace(candidate, "implementation.rs")
        validate_agent_workspace(plan_dir, "plan.md")

        def evaluate() -> dict[str, Any]:
            try:
                check_candidate(
                    candidate_path.read_text(encoding="utf-8")
                )
            except ValueError as error:
                # An invalid candidate is iteration feedback, not a controller
                # setup failure.  Codex must be allowed to repair even a seed
                # that does not yet have the required concurrent shape.
                return {
                    "success": False,
                    "stage": "candidate-preflight",
                    "reason": str(error),
                    "stdout": "",
                    "stderr": "",
                }
            return verify(
                candidate,
                interface=run_dir / "contract" / "interface" / "mod.rs",
                test=run_dir / "contract" / "tests" / "database_test.rs",
                verus=args.verus,
                z3=args.z3,
                timeout=args.verification_timeout,
            )

        completed = completed_iterations(run_dir)
        last_folder = run_dir / "iterations" / f"{completed:03d}"
        if (args.dry_run and completed > 0
                and candidate_path.read_bytes() == (last_folder / "implementation.rs").read_bytes()):
            result = json.loads((last_folder / "verification.json").read_text(encoding="utf-8"))
        else:
            result = evaluate()
        if not (run_dir / "iterations" / "000").exists():
            save_iteration(run_dir, 0, result)
        best_progress_result, best_progress_candidate, best_progress_iteration = (
            best_progress_snapshot(
                run_dir,
                result,
                candidate_path.read_bytes(),
            )
        )
        best: dict[str, Any] | None = None
        lines = source_lines(candidate_path)
        if is_better(result, lines, best):
            best = {"iteration": completed, "nonempty_lines": lines, "verification": result}
            (run_dir / "best").mkdir(parents=True, exist_ok=True)
            shutil.copy2(candidate_path, run_dir / "best" / "implementation.rs")
        summary = result.get("summary") or {}
        print(
            f"[{completed:03d}] current success={result.get('success')} "
            f"verified={summary.get('verified')} errors={summary.get('errors')}",
            flush=True,
        )

        if args.verify_only or (result.get("success") and not args.keep_going):
            last_iteration = completed
        else:
            last_iteration = args.iterations

        codex = ""
        toolchain = ""
        codex_environment = dict(os.environ)
        if args.codex_home:
            codex_home = args.codex_home.resolve()
            codex_home.mkdir(parents=True, exist_ok=True)
            codex_environment["CODEX_HOME"] = str(codex_home)
        if completed < last_iteration:
            verus_path = resolve_executable(args.verus, "VERUS", "verus")
            z3_path = resolve_executable(
                args.z3, "VERUS_Z3_PATH", str(verus_path.with_name("z3.exe"))
            )
            toolchain = pinned_toolchain_context(verus_path, z3_path)
            if not args.dry_run:
                codex = resolve_command(args.codex)
                check_codex_login(codex, codex_environment)

        if completed:
            print(f"Resuming after iteration {completed}; total budget is {args.iterations}.", flush=True)

        if args.dry_run and completed < last_iteration:
            preview = run_dir / "preview"
            preview.mkdir(parents=True, exist_ok=True)
            (preview / "planner.prompt.md").write_text(
                build_planner_prompt(run_dir, completed + 1, result, toolchain), encoding="utf-8"
            )
            (preview / "coder.prompt.md").write_text(
                build_prompt(run_dir, completed + 1, result, toolchain), encoding="utf-8"
            )
            print(f"Dry run: prompts saved under {preview}; no iteration was consumed.")
            return 0

        for number in range(completed + 1, last_iteration + 1):
            load_manifest(run_dir)
            started_at = time.time()
            partial = run_dir / "in_progress"
            partial.mkdir()
            plan_before = plan_path.read_bytes()
            code_before = candidate_path.read_bytes()
            write_round_file(partial, "plan.before.md", plan_before)
            write_round_file(partial, "implementation.before.rs", code_before)
            planner_succeeded = False
            plan_after = b""
            planner_code = 1
            planner_stdout = ""
            planner_stderr = ""
            for planner_attempt in range(1, args.planner_retries + 1):
                # A failed Planner may leave an empty or partial plan behind.
                # Restore the round's starting plan before every retry.
                plan_path.write_bytes(plan_before)
                planner_prompt = build_planner_prompt(run_dir, number, result, toolchain)
                if planner_attempt > 1:
                    planner_prompt += f"""

PLANNER RETRY
-------------
This is retry {planner_attempt} of {args.planner_retries} for the same iteration.
The previous attempt did not leave an actionable plan.md. Edit plan.md directly,
preserve the required headings, and do not only describe what you would do.
"""
                write_round_file(
                    partial,
                    f"planner.attempt-{planner_attempt}.prompt.md",
                    planner_prompt,
                )
                print(
                    f"[{number:03d}] Planner started (attempt "
                    f"{planner_attempt}/{args.planner_retries})",
                    flush=True,
                )
                planner_code, planner_stdout, planner_stderr = run_codex(
                    codex, plan_dir, planner_prompt, model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    timeout=args.agent_timeout, environment=codex_environment,
                )
                write_round_file(
                    partial,
                    f"planner.attempt-{planner_attempt}.stdout.jsonl",
                    planner_stdout,
                )
                write_round_file(
                    partial,
                    f"planner.attempt-{planner_attempt}.stderr.log",
                    planner_stderr,
                )
                load_manifest(run_dir)
                validate_agent_workspace(plan_dir, "plan.md")
                if candidate_path.read_bytes() != code_before:
                    raise ValueError("Planner modified implementation.rs")
                candidate_plan = plan_path.read_bytes()
                actionable = (
                    planner_code == 0
                    and candidate_plan != plan_before
                    and bool(candidate_plan.strip())
                )
                if actionable:
                    plan_after = candidate_plan
                    planner_succeeded = True
                    break
                plan_path.write_bytes(plan_before)
                reason = (
                    f"Planner attempt {planner_attempt} failed: "
                    f"returncode={planner_code}, actionable={actionable}\n"
                )
                write_round_file(
                    partial,
                    f"planner.attempt-{planner_attempt}.failure.txt",
                    reason,
                )
                if planner_attempt < args.planner_retries:
                    print(
                        f"[{number:03d}] Planner produced no actionable plan; retrying",
                        flush=True,
                    )
                    time.sleep(2)
            if not planner_succeeded:
                # Do not stop the automated loop merely because the Planner
                # failed to produce a new design.  Keep the last known plan;
                # the unchanged-plan history is itself evidence for the next
                # Planner session to trigger a design pivot.
                plan_after = plan_before
                write_round_file(
                    partial,
                    "planner.fallback.txt",
                    "No actionable plan was produced after "
                    f"{args.planner_retries} attempts; continued with the "
                    "previous plan.\n",
                )
                print(
                    f"[{number:03d}] Planner produced no new plan; "
                    "continuing with the previous plan",
                    flush=True,
                )
            write_round_file(partial, "planner.prompt.md", planner_prompt)
            write_round_file(partial, "planner.stdout.jsonl", planner_stdout)
            write_round_file(partial, "planner.stderr.log", planner_stderr)
            write_round_file(partial, "plan.after.md", plan_after)
            write_round_file(partial, "plan.diff", unified_diff(plan_before, plan_after, "plan.md"))
            planner_status = (
                "updated plan.md" if planner_succeeded
                else "is using the previous plan"
            )
            print(
                f"[{number:03d}] Planner {planner_status}; Coding Agent started",
                flush=True,
            )
            coder_succeeded = False
            code = 1
            stdout = ""
            stderr = ""
            code_after = code_before
            for coder_attempt in range(1, args.coder_retries + 1):
                # A failed Coding Agent may leave a partial candidate behind.
                # Restore the round's starting candidate before every retry.
                candidate_path.write_bytes(code_before)
                coder_prompt = build_prompt(run_dir, number, result, toolchain)
                if coder_attempt > 1:
                    coder_prompt += f"""

CODING AGENT RETRY
------------------
This is retry {coder_attempt} of {args.coder_retries} for the same iteration.
The previous attempt did not complete successfully. Make one bounded change,
edit implementation.rs directly, and leave the plan.md file untouched.
"""
                write_round_file(
                    partial,
                    f"coder.attempt-{coder_attempt}.prompt.md",
                    coder_prompt,
                )
                print(
                    f"[{number:03d}] Coding Agent started (attempt "
                    f"{coder_attempt}/{args.coder_retries})",
                    flush=True,
                )
                code, stdout, stderr = run_codex(
                    codex, candidate, coder_prompt, model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    timeout=args.agent_timeout, environment=codex_environment,
                )
                write_round_file(
                    partial,
                    f"coder.attempt-{coder_attempt}.stdout.jsonl",
                    stdout,
                )
                write_round_file(
                    partial,
                    f"coder.attempt-{coder_attempt}.stderr.log",
                    stderr,
                )
                load_manifest(run_dir)
                validate_agent_workspace(candidate, "implementation.rs")
                if plan_path.read_bytes() != plan_after:
                    raise ValueError("Coding Agent modified plan.md")
                if code == 0:
                    code_after = candidate_path.read_bytes()
                    coder_succeeded = True
                    break
                candidate_path.write_bytes(code_before)
                if coder_attempt < args.coder_retries:
                    print(
                        f"[{number:03d}] Coding Agent failed; retrying",
                        flush=True,
                    )
                    time.sleep(2)
            if not coder_succeeded:
                # Preserve the candidate and let the next automated iteration
                # retry with the verifier evidence.  This is a completed
                # fallback round, not an interrupted partial round.
                code_after = code_before
                write_round_file(
                    partial,
                    "coder.fallback.txt",
                    "Coding Agent did not complete after "
                    f"{args.coder_retries} attempts; continued with the "
                    "previous candidate.\n",
                )
                print(
                    f"[{number:03d}] Coding Agent did not complete; "
                    "continuing with the previous candidate",
                    flush=True,
                )
            write_round_file(partial, "coder.prompt.md", coder_prompt)
            write_round_file(partial, "coder.stdout.jsonl", stdout)
            write_round_file(partial, "coder.stderr.log", stderr)
            write_round_file(partial, "implementation.after.rs", code_after)
            write_round_file(partial, "implementation.diff", unified_diff(
                code_before, code_after, "implementation.rs"
            ))
            print(f"[{number:03d}] Coding Agent finished; Verus started", flush=True)
            result = evaluate()
            result["planner_returncode"] = planner_code
            result["codex_returncode"] = code
            result["controller_fallback"] = not planner_succeeded or not coder_succeeded
            write_round_file(partial, "verus.stdout.log", str(result.get("stdout", "")))
            write_round_file(partial, "verus.stderr.log", str(result.get("stderr", "")))
            write_round_file(partial, "verification.json", json.dumps(
                result, ensure_ascii=False, indent=2
            ) + "\n")
            write_round_file(partial, "implementation.rs", code_after)
            write_round_file(partial, "metadata.json", json.dumps({
                "iteration": number,
                "model": args.model,
                "planner_returncode": planner_code,
                "coder_returncode": code,
                "plan_before_sha256": digest(plan_before),
                "plan_after_sha256": digest(plan_after),
                "implementation_before_sha256": digest(code_before),
                "implementation_after_sha256": digest(code_after),
                "started_at_unix": started_at,
                "finished_at_unix": time.time(),
            }, ensure_ascii=False, indent=2) + "\n")
            folder = run_dir / "iterations" / f"{number:03d}"
            if folder.exists():
                raise ValueError(f"iteration already exists: {folder}")
            folder.parent.mkdir(parents=True, exist_ok=True)
            partial.rename(folder)
            current_progress = proof_progress(result)
            if current_progress > proof_progress(best_progress_result):
                best_progress_result = result
                best_progress_candidate = code_after
                best_progress_iteration = number
            lines = source_lines(candidate_path)
            if is_better(result, lines, best):
                best = {"iteration": number, "nonempty_lines": lines, "verification": result}
                (run_dir / "best").mkdir(parents=True, exist_ok=True)
                shutil.copy2(folder / "implementation.rs", run_dir / "best" / "implementation.rs")
            summary = result.get("summary") or {}
            print(
                f"[{number:03d}] planner={planner_code} coder={code} success={result.get('success')} "
                f"verified={summary.get('verified')} errors={summary.get('errors')} lines={lines}",
                flush=True,
            )
            if result.get("success") and not args.keep_going:
                break

        state = {
            "format": 2,
            "finished_at_unix": time.time(),
            "contract": manifest,
            "best": best,
            "best_progress": {
                "iteration": best_progress_iteration,
                "score": proof_progress(best_progress_result),
                "verification": best_progress_result,
            },
            "last_verification": result,
        }
        (run_dir / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if best:
            print(
                f"Best verified candidate: iteration {best['iteration']} "
                f"({best['nonempty_lines']} non-empty lines)"
            )
            print(args.run_dir / "best" / "implementation.rs")
            return 0
        print(
            "No verified candidate was found. Inspect iterations/*/verification.json.",
            file=sys.stderr,
        )
        return 1
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        if (run_dir / "in_progress").is_dir():
            try:
                archived = archive_interrupted_round(run_dir)
                print(f"Interrupted attempt archived at {archived}", file=sys.stderr)
            except OSError as recovery_error:
                print(f"could not restore interrupted attempt: {recovery_error}", file=sys.stderr)
        print(f"setup error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
