"""Small cross-platform helpers used by the SkySynth command-line workflow."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def bash_executable() -> str:
    """Return a Bash suitable for running SkySynth's portable ``test.sh`` files.

    On Windows, ``shutil.which('bash')`` often finds the WSL launcher in
    ``System32``.  That process cannot reliably consume native Windows paths
    passed through ``SKYDISCOVER_IMPL`` and ``SKYDISCOVER_INTERFACE``.  Prefer
    Git for Windows' Bash instead.  ``SKYDISCOVER_BASH`` is an explicit escape
    hatch for non-standard installations.
    """

    override = os.environ.get("SKYDISCOVER_BASH")
    if override:
        resolved = shutil.which(override) or override
        path = Path(resolved).expanduser()
        if path.is_file():
            return str(path.resolve())
        raise FileNotFoundError(f"SKYDISCOVER_BASH does not name a file: {override}")

    if os.name != "nt":
        resolved = shutil.which("bash")
        if resolved:
            return resolved
        raise FileNotFoundError("bash is required to run SkySynth test.sh suites")

    candidates: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        root = os.environ.get(variable)
        if root:
            candidates.extend(
                (
                    Path(root) / "Git" / "bin" / "bash.exe",
                    Path(root) / "Programs" / "Git" / "bin" / "bash.exe",
                )
            )

    git = shutil.which("git")
    if git:
        git_path = Path(git).resolve()
        # Common layouts: <Git>/cmd/git.exe and <Git>/bin/git.exe.
        candidates.append(git_path.parent.parent / "bin" / "bash.exe")

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate.resolve())

    resolved = shutil.which("bash")
    if resolved and "windows\\system32" not in str(Path(resolved)).lower():
        return resolved
    raise FileNotFoundError(
        "Git Bash is required on Windows. Install Git for Windows or set "
        "SKYDISCOVER_BASH to bash.exe."
    )
