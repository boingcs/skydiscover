"""SkySynth adapter for the pinned concurrent atomic-contract proof."""

from __future__ import annotations

import importlib.util
import os
import sys
from importlib import resources
from pathlib import Path


def _load_checker():
    checker = (
        Path(str(resources.files("skydiscover")))
        / "synthesize"
        / "examples"
        / "verus-db-windows"
        / "verify_candidate.py"
    )
    spec = importlib.util.spec_from_file_location("skysynth_verus_checker", checker)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the Verus proof checker at {checker}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    impl = Path(os.environ["SKYDISCOVER_IMPL"])
    interface = Path(os.environ["SKYDISCOVER_INTERFACE"]) / "mod.rs"
    test = Path(__file__).resolve().with_name("database_test.rs")
    checker = _load_checker()
    try:
        result = checker.verify(
            impl,
            interface=interface,
            test=test,
            verus=os.environ.get("VERUS"),
            z3=os.environ.get("VERUS_Z3_PATH"),
        )
    except (OSError, RuntimeError, ValueError) as error:
        print("VERUS FAILED: preflight", file=sys.stderr)
        print(str(error), file=sys.stderr)
        return 1
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
