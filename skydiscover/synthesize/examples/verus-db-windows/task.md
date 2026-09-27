---
domain: verified concurrent database
checked_by: proof
evaluation: verification
platform: windows
---

# Build and prove a concurrent in-memory database in Verus

Use SkySynth's formal proof loop. Write one candidate module at
`synthesis/impl/implementation.rs`. The candidate must contain both the executable
Rust implementation and the Verus proof that the implementation satisfies the
immutable atomic contract in `evaluator/mod.rs`.

## Fixed concurrent specification

`DatabaseState` is the abstract sequential state: a ghost
`Map<Seq<char>, i32>` identified by one `GhostVar` location. The `impl_db!` macro
defines atomic contracts for four concurrent operations:

- `get(key)` linearizes without changing the abstract map and returns the value
  present at its linearization point;
- `put(key, value)` linearizes by replacing or inserting exactly that mapping;
- `scan(lo, hi)` linearizes without changing the map and returns every and only
  entry in the inclusive range, in strict key order;
- `sort()` linearizes without changing the map and returns every mapping exactly
  once, in strict key order.

The candidate must use `impl_db!` for all four method bodies. Each body receives
its `*_lp` proof object and must consume it exactly once at the real executable
linearization point. Proving only a separate ghost model is not sufficient: the
proof must connect the concrete shared representation to `DatabaseState` at the
same step that determines the operation's result or update.

## Required candidate shape

Define a public `VerifiedDb` that is safely shareable by threads, together with:

```rust
pub open spec fn id(&self) -> Loc;

pub fn new() -> (out: (Self, Tracked<DatabaseState>))
    ensures
        out.1@.linked(out.0.id()),
        out.1@.contents == Map::<Seq<char>, i32>::empty();
```

Instantiate the fixed `impl_db!` macro for `VerifiedDb`. Use Verus-verifiable
concurrency primitives and invariants. Do not replace the task with a purely
sequential `&mut self` implementation, a detached model, or a trusted wrapper.

## Verification boundary

Correctness is the only objective. The candidate must verify with
`--no-cheating`. Do not use `assume`, `admit`, axioms, `external_body`, unsafe
code, source inclusion, custom macros, conditional compilation, or other proof
escape hatches. Runtime code and proof code must remain in the candidate module.

The proof establishes safety and operation-level linearizability with respect to
the abstract map. It does not by itself establish deadlock freedom, starvation
freedom, wait freedom, crash consistency, persistence, or performance.

The evaluator stages the immutable concurrent spec, constructor-shape check and
candidate in an empty temporary directory. Delivery succeeds only when Verus
verifies the complete crate with zero errors and the compiled executable runs.
