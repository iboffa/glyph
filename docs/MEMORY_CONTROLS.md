# Allocation contracts and explicit storage

The default remains shared, nonmoving BDWGC storage. This release adds checked
allocation contracts and two **restricted, explicit** storage domains to both
frontends. These are language additions, not a GC-disable setting. Allocation
control does not guarantee freedom from GC pauses: another registered thread can
trigger a stop-the-world collection.

## Allocation contracts

```glyph
@noalloc total x:int>int
  values := fill(4, x)
  ret sum(values)
```

`@noalloc` precedes a function or record method, on the same line or the previous
line. It is checked after imports, generic specialization and ordinary typing.
The compiler must prove the function and its transitive callees do not allocate
heap storage on successful execution. Bounded stack arrays and scalar closure
environments are allowed. Fused reductions which create no buffer are allowed.
Managed, arena and owned allocations are all heap allocations and are rejected.
Unknown runtime operations, unknown callbacks and recursive call graphs are
rejected conservatively, even when a particular invocation would not allocate.
The worker builtin allowlist is **not** used as an allocation or purity proof.

The contract covers user code and its called runtime operations, excluding
process startup, collector internals and terminal error reporting. An overflow,
invalid size or bounds failure still reports the existing runtime diagnostic and
terminates; diagnostics may use libc resources. The contract is neither a total
stack-space bound nor a real-time guarantee. `print`, string formatting and
collection constructors are rejected. Generics are checked per instantiation.

`--no-optimize` disables optional frontend transformations for ordinary programs.
When a program declares allocation contracts, proven allocation-eliminating
lowerings remain enabled so disabling optimization does not invalidate its
contract. C optimization levels `-O0`–`-O3` do not change these safety rules.

## Scoped arenas

```glyph
copy_values n:int>[int]
  arena
    values := arena_fill(n, 3)
    values[0] = 7
    ret managed(values)
```

An `arena` block owns a linked set of aligned chunks, normally 64 KiB each.
`arena_fill(length, value)` explicitly allocates in the innermost arena. Normal
block completion and early return reclaim all its chunks. Nested arenas have
independent lifetimes. Returns evaluate their value before cleanup, in reverse
lexical cleanup order, including task scopes and owned buffers. Glyph has no
exceptions, break or continue statements. Terminal traps and `exit` terminate
the process; OS process teardown releases its storage.

The first implementation accepts **only int, f64 and bool elements**. Strings,
records (including pointer-free records), unions, arrays, function values,
channels and managed references as elements are explicitly rejected. This
restriction prevents malloc storage from hiding references from the collector;
it does not pretend that unregistered malloc memory is scanned.

Arena arrays are inferred local bindings. They may be indexed, modified, folded,
iterated and used by audited read-only builtins. They cannot be returned, assigned
to another binding, inserted in a container/record, captured by a closure, passed
to an arbitrary function, sent through a channel, passed to a task, or exposed
through `ptr`, including in `unsafe`. No implicit promotion occurs. `managed(a)`
(or `clone(a)`) makes an explicit fresh managed copy which can survive the scope.
Only primitive arrays support `managed` in this release.

## Owned buffers and scoped borrowing

```glyph
main>void
  owner := owned_fill(4, 2)
  borrow values = owner
    values[0] = 9
    print(sum(values))
  next := move(owner)
  free(next)
```

`owned_fill` allocates primitive malloc storage. Its inferred `buffer[T]` type is
an affine owner, not an ordinary array descriptor. Owners cannot be copied,
stored in records/collections, returned, captured or declared in parameter/type
signatures. `move(owner)` transfers ownership into a fresh local in the same
lexical block, invalidating the original binding. `free(owner)` releases it and
invalidates that binding. The checker rejects use after move/free and double-free.
A live local owner is also freed automatically at block exit, including return;
explicit free/move clear its emitted descriptor to make cleanup idempotent.

`borrow name = owner` opens a unique mutable array borrow. The owner cannot be
used, freed, moved or borrowed again while that borrow is active. Borrowed
references have the same escape restrictions as arena arrays. `managed(borrow)`
copies surviving results. A branch, loop or nested block may own/free its own
buffers, but consuming an outer owner across that control-flow boundary is
rejected. This intentionally avoids unsound merging of ownership states.

There is no unchecked escape hatch for these domains. Existing unsafe pointer
operations remain available on ordinary managed primitive arrays; their stable
pointer and interior-pointer retention guarantees are unchanged. Explicit
storage is not currently available inside worker callbacks: the existing worker
effect checker rejects these new runtime operations. Managed values and automatic
stack promotion inside existing safe workers retain their previous guarantees.

## Compatibility and restrictions

`arena`, `borrow`, `@noalloc`, `arena_fill`, `owned_fill`, `move`, `free` and
`managed` introduce new syntax or builtin meanings. In particular, prior
functions named after the new builtins require renaming, and `arena`/`borrow`
at the beginning of a statement now introduce blocks. Existing shared arrays,
shallow clones, string slices, value records and pointer operations otherwise
keep their semantics. These deliberate syntax changes and unsupported escape
paths have compile-time regression coverage in `tests/test_memory_controls.py`.

Explicit memory controls are deliberately narrower than a general borrow checker.
Cross-function ownership transfer, region polymorphism, borrowed parameters,
reference-bearing region layouts and concurrent publication are not supported.
They require additional lifetime/collector-root proofs, not a permissive cast.

## Optimization implementation

The reference compiler lowers the checked tree into typed regions with source
locations, ordered operands and explicit conditional/loop/lambda bodies. Effect
summaries consume this representation. The native frontend uses its existing
typed, indexed node regions with separate analysis tables. Both preserve the
established explicit sequencing of emitted C.

Implemented transformations are conservative:

- Primitive literal/fill/range arrays with constant extents of at most 128 elements
  can use stack storage when every use is in the audited nonescaping grammar.
  A function has a 4096-byte allocation-site budget. Scalar-only closure
  environments receive the same treatment; immutable local closure calls can
  target their implementation directly.
- An unaliased primitive local repeatedly replaced by `fill` can reuse its old
  buffer only when lengths match. Different lengths allocate normally. Aliases,
  captures, pointer extraction and arbitrary callees disable this transformation.
- Immediate builtin `sum(fill(...))`, `count(fill(...))` and `sum(range(...))`
  eliminate the temporary buffer. Length/value expressions still evaluate once
  in the original order; size validation precedes the reduction. Integer prefixes
  remain checked, and floating-point additions remain ordered. A user-defined
  `sum` or `count` is never treated as an intrinsic.
- Constant index/extent proofs remove bounds checks. Literal interval proofs
  remove overflow helpers only when the complete result fits i64. The native
  frontend currently uses a narrower small-literal proof. Dynamic checks remain.
- Completely overwritten pointer-free construction/clone/range storage may skip
  redundant zeroing. Reference-bearing allocations remain cleared before a
  collector scan. No general definite-initialization claim is made.

Allocation/effect summaries are conservative across direct calls; unknown calls
and recursive graphs become unknown/allocating. The reference report also records
coarse mutation, escape and alias facts. These are whole-function overapproximations,
not parameter-level lifetime summaries. Arbitrary callback fusion, dynamic range
inference and general interprocedural stack promotion remain unsupported.

`glyph build file.gly --opt-report build/report.json` and the native driver's
same option report accepted/rejected stack decisions; the reference report also
explains reuse, fusion, callback and check proofs. Native reports currently expose
allocation summaries and stack decisions rather than all reference report fields.
`--zero-init` restores clearing for allocation-ablation experiments. It does not
turn off stack promotion or fusion. `--alloc-stats` and `--gc-timing` enable separate,
opt-in instrumentation; see the measurement methodology below.
