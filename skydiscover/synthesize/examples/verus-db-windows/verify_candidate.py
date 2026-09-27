"""Independently verify one concurrent Verus database candidate on Windows.

The verifier stages the immutable contract, test, and candidate in a fresh temporary
directory, rejects common proof escape hatches, runs Verus with ``--no-cheating``,
then starts the compiled constructor-shape harness. It deliberately has no dependency on
Bash, fcntl, bwrap, or the rest of the SkySynth runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_INTERFACE = HERE / "evaluator" / "mod.rs"
DEFAULT_TEST = HERE / "evaluator" / "tests" / "database_test.rs"

# The loop must prove the user-supplied concurrent contract, not a candidate-edited
# weakening of it. Hash canonical UTF-8/LF bytes so Windows line endings do not
# change the identity of the fixed theorem statement.
EXPECTED_CONTRACT_SHA256 = "a024f4e03dec8d6673affe40027ba57417705e65017a18090f086ad54c436a59"
EXPECTED_TEST_SHA256 = "945624786a0ee5c67b0c50a9c5f5a89554124868c0f613cce780652768757429"

# These are rejected even in comments so a generated candidate cannot hide an
# escape hatch from a simple review or from a later scanner.
FORBIDDEN = {
    "admit",
    "assume",
    "assume_specification",
    "assume_termination",
    "axiom",
    "exec_allows_no_decreases_clause",
    "external",
    "external_body",
    "include",
    "include_str",
    "inline_air_stmt",
    "macro_rules",
    "no_verify",
    "trusted",
    "unsafe",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def lf_bytes(path: Path) -> bytes:
    """Read a text file and return canonical UTF-8/LF bytes on every host."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def check_candidate(source: str) -> None:
    for word in sorted(FORBIDDEN):
        if re.search(r"\b" + re.escape(word) + r"\b", source):
            raise ValueError(f"forbidden proof shortcut or escape hatch: {word}")
    # Required-shape markers must occur in code, not merely in a comment that
    # attempts to satisfy the textual preflight check.
    code = re.sub(r"//[^\n]*|/\*.*?\*/", "", source, flags=re.DOTALL)
    required = {
        r"\bVerifiedDb\b": "candidate does not define VerifiedDb",
        r"\bimpl_db\s*!\s*\{": "candidate does not instantiate the fixed impl_db! atomic contract",
        r"\bpub\s+fn\s+new\b": "candidate does not provide the required public constructor",
        r"\bfn\s+id\b": "candidate does not expose the GhostVar location through id()",
    }
    for pattern, message in required.items():
        if re.search(pattern, code) is None:
            raise ValueError(message)


def verification_summary(stdout: str) -> dict[str, Any] | None:
    """Return Verus's one complete JSON verification summary, if present."""
    decoder = json.JSONDecoder()
    found: list[dict[str, Any]] = []
    for index, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("verification-results"), dict):
            found.append(value["verification-results"])
    return found[0] if len(found) == 1 else None


def resolve_executable(value: str | None, env_name: str, fallback: str) -> Path:
    requested = value or os.environ.get(env_name) or fallback
    resolved = shutil.which(requested)
    path = Path(resolved or requested).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"executable not found for {env_name}: {requested}")
    return path


def verify(
    candidate_dir: Path,
    *,
    interface: Path = DEFAULT_INTERFACE,
    test: Path = DEFAULT_TEST,
    verus: str | None = None,
    z3: str | None = None,
    timeout: int = 240,
) -> dict[str, Any]:
    candidate_path = candidate_dir.resolve()
    candidate = candidate_path if candidate_path.is_file() else candidate_path / "implementation.rs"
    if not candidate.is_file():
        raise ValueError(f"candidate is missing {candidate}")

    source = candidate.read_text(encoding="utf-8")
    check_candidate(source)
    contract_bytes = lf_bytes(interface.resolve())
    test_bytes = lf_bytes(test.resolve())
    if sha256(contract_bytes) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("immutable concurrent contract changed")
    if sha256(test_bytes) != EXPECTED_TEST_SHA256:
        raise ValueError("immutable constructor-shape test changed")
    verus_path = resolve_executable(verus, "VERUS", "verus")
    z3_path = resolve_executable(z3, "VERUS_Z3_PATH", str(verus_path.with_name("z3.exe")))
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="skydiscover-verus-windows-") as raw:
        build = Path(raw)
        (build / "spec").mkdir()
        (build / "impl").mkdir()
        (build / "spec" / "mod.rs").write_bytes(contract_bytes)
        (build / "database_test.rs").write_bytes(test_bytes)
        (build / "impl" / "implementation.rs").write_bytes(
            source.replace("\r\n", "\n").encode("utf-8")
        )

        binary = build / ("database.exe" if os.name == "nt" else "database")
        command = [
            str(verus_path),
            "database_test.rs",
            "--crate-type",
            "bin",
            "--crate-name",
            "skydiscover_verus_database",
            "--no-cheating",
            "--output-json",
            "--expand-errors",
            "--multiple-errors",
            "10",
            "--triggers-mode",
            "silent",
            "--rlimit",
            "10",
            "--num-threads",
            "1",
            "--compile",
            "-o",
            str(binary),
        ]
        env = os.environ.copy()
        env["VERUS_Z3_PATH"] = str(z3_path)
        for name in ("VERUS_EXTRA_ARGS", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"):
            env.pop(name, None)

        try:
            process = subprocess.run(
                command,
                cwd=build,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            return {
                "success": False,
                "stage": "verify",
                "reason": f"Verus timed out after {timeout}s",
                "stdout": error.stdout or "",
                "stderr": error.stderr or "",
                "candidate_sha256": sha256(source.encode("utf-8")),
                "elapsed_seconds": time.perf_counter() - started,
            }

        summary = verification_summary(process.stdout)
        success = bool(
            process.returncode == 0
            and summary
            and summary.get("success") is True
            and summary.get("is-verifying-entire-crate") is True
            and isinstance(summary.get("verified"), int)
            and summary["verified"] > 0
            and summary.get("errors") == 0
            and summary.get("encountered-error") is False
            and summary.get("encountered-vir-error") is False
            and binary.is_file()
        )
        result: dict[str, Any] = {
            "success": success,
            "stage": "verify",
            "returncode": process.returncode,
            "summary": summary,
            "stdout": process.stdout,
            "stderr": process.stderr,
            "command": command,
            "candidate_sha256": sha256(source.encode("utf-8")),
            "contract_sha256": sha256(contract_bytes),
            "test_sha256": sha256(test_bytes),
            "elapsed_seconds": time.perf_counter() - started,
        }
        if not success:
            result["reason"] = "Verus did not completely verify and compile the candidate"
            return result

        try:
            runtime = subprocess.run(
                [str(binary)],
                cwd=build,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
        except subprocess.TimeoutExpired as error:
            result.update(
                success=False,
                stage="runtime",
                reason="compiled contract exercise timed out",
                runtime_stdout=error.stdout or "",
                runtime_stderr=error.stderr or "",
            )
            return result
        result.update(
            success=runtime.returncode == 0,
            stage="complete" if runtime.returncode == 0 else "runtime",
            runtime_returncode=runtime.returncode,
            runtime_stdout=runtime.stdout,
            runtime_stderr=runtime.stderr,
            elapsed_seconds=time.perf_counter() - started,
        )
        if runtime.returncode:
            result["reason"] = "compiled contract exercise failed"
        return result


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--candidate", type=Path, required=True)
    command.add_argument("--interface", type=Path, default=DEFAULT_INTERFACE)
    command.add_argument("--test", type=Path, default=DEFAULT_TEST)
    command.add_argument("--verus")
    command.add_argument("--z3")
    command.add_argument("--timeout", type=int, default=240)
    command.add_argument("--json", action="store_true")
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = verify(
            args.candidate,
            interface=args.interface,
            test=args.test,
            verus=args.verus,
            z3=args.z3,
            timeout=args.timeout,
        )
    except (OSError, UnicodeError, ValueError) as error:
        result = {"success": False, "stage": "setup", "reason": str(error)}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "PASSED" if result.get("success") else "FAILED"
        print(f"VERUS {status}: {result.get('stage')}")
        summary = result.get("summary") or {}
        if summary:
            print(f"verified={summary.get('verified')} errors={summary.get('errors')}")
        if result.get("reason"):
            print(result["reason"], file=sys.stderr)
        if not result.get("success"):
            print(result.get("stdout", ""), end="")
            print(result.get("stderr", ""), end="", file=sys.stderr)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
