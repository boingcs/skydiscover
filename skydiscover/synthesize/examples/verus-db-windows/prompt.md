Continue the formal-proof-driven synthesis run for the concurrent Verus database
described by the immutable task and contract supplied below.

This is a correctness-only, headless run. Do not ask for a performance budget and
do not create a benchmark. Treat the supplied task, interface, and client test as
immutable. Work only on the candidate `implementation.rs` in the current working
directory.

You are the Coding Agent. The controller runs a separate Planner first and supplies
its current `plan.md` below. Implement one bounded step from `## Brief` while using
the Verus feedback as the source of truth. Do not edit the plan.

Use the SkySynth formal IDS discipline:

The controller supplies a `PINNED VERUS TOOLCHAIN` section in every iteration.
Use its absolute paths to inspect the exact local Verus and vstd source before
changing atomic APIs, token-state-machine APIs, or Verus syntax. The Windows
agent environment may not provide `rg`; use PowerShell `Get-Content`,
`Select-String`, and `Get-ChildItem` instead. Do not guess a macro or helper
name when the pinned source can settle it.

1. Co-design the executable concurrent representation and its Verus proof.
2. Make one bounded, testable proof-repair step in this invocation.
3. Use the previous independent Verus result as evidence.
4. Preserve working parts of the candidate and revise the smallest blocking part.
5. Do not merely describe a patch; edit `implementation.rs` itself.
6. Do not use `assume`, `admit`, axioms, `external_body`, unsafe code, source
   inclusion, custom macros, conditional compilation, or another proof escape
   hatch.
7. Keep the real executable operation and its abstract transition coupled at the
   operation's linearization point.
8. Stop this invocation after the bounded repair step. The controller will run the
   immutable checker and start another invocation if the proof is still incomplete.

The final success condition is independent verification of the complete staged
crate with Verus `--no-cheating`, zero errors, and a compiled client that starts
successfully.
