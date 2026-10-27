# Implementation and tradeoffs

The environment initially had Python 3.12 and Node.js, no compiler on PATH, and an empty Git workspace. The implementation uses Python 3.11+ and pinned `ziglang==0.14.1`, whose `zig cc` includes Clang/LLVM and a linker. Standalone Clang is a fallback. The compiler frontend has no Python dependencies; benchmark dependencies are optional.

Pipeline: UTF-8 source → indentation tokens with spans → recursive-descent statements/Pratt expressions → typed AST → explicitly sequenced C → Clang LLVM optimizer → native executable. There is no interpreter, Python runtime or VM in the output. The generated C includes the small runtime header and is left beside the executable for inspection. User identifiers receive separate `v_`/`f_` prefixes. String bytes are emitted with fixed-width octal escapes to avoid C source injection and escape-boundary ambiguity.

In the reference Python frontend, `syntax.py` owns syntax and diagnostic data. `checker.py` owns types, lexical scopes, builtin signatures, unsafe checks and conservative return analysis. `backend.py` sequences potentially effectful expressions into temporaries; LLVM removes unnecessary temporaries. This intentionally avoids depending on C's unspecified argument evaluation order. Boolean short-circuit expressions lower to control flow. Array indexing and integer arithmetic lower to runtime helpers with source locations. `runtime.h` implements allocation, checked math, output and clocks. `formatter.py` is an AST printer, independent of type checking. `cli.py` supplies the installed `glyph` entry point.

`selfhost/compiler.gly` implements a second frontend and C emitter in Glyph.
Tokens and AST nodes use source-sized arrays, with integer node indices and
record values. Symbol lookup is currently linear. Small per-node/parameter
collections use existing immutable `push`; output uses a preallocated string
array and a final join. This allows the compiler to compile itself without
changing array aliasing or stable pointer storage. Temporary compiler data now uses the same default tracing collector as other Glyph programs.

`stdlib.py` declares the new fixed builtin signatures; `std_runtime.h` implements
UTF-8/text, file and POSIX process operations. `io_runtime.h` adds binary and
chunked file operations with explicit close and never-reused integer handles.
`json_runtime.h` validates and navigates JSON text through temporary collected
trees, preserving number lexemes. Both emitters embed these headers. Generated programs use these
runtime primitives directly. The native compiler implements parsing, semantic
analysis and code generation in Glyph, not in special compiler-only C helpers.
The native driver invokes a C compiler with an argument vector and no shell.
`selfhost/bootstrap.py` checks a three-stage fixed point; `selfhost/verify.py`
runs native checking and C emission against the existing tests while retaining
the Python checker as a differential reference. See [self-hosting](SELF_HOSTING.md).

C lowering trades direct LLVM control for portability, an inspectable intermediate artifact and a small frontend. It is a real ahead-of-time compiler using LLVM indirectly. Backend diagnostics are wrapped as G202; they indicate a compiler/environment issue, not a normal user type error. LLVM can inline helpers and remove redundant bounds checks. Checked addition may constrain vectorization; benchmarks compare it against ordinary C on inputs whose arithmetic cannot overflow. Both use `-O2 -fno-fast-math -ffp-contract=off`; no promise of equal machine code is made across arbitrary programs.

The default allocator is the bundled BDWGC 8.2.12 nonmoving tracing collector. Numeric/boolean arrays, pointer-free record arrays and string bytes use atomic allocations; reference-bearing arrays use scanned allocations. Both emitters classify record layouts recursively. Collection preserves shared descriptors, cycles and interior pointers without ownership syntax. `gc_support.py` caches the collector object for Python builds; the native driver compiles the vendored amalgamation directly. See [memory management](MEMORY.md) for constraints and build details. Direct LLVM IR, more standard-library operations, incremental compilation and debug information remain future work. A second human presentation layer is deliberately deferred. The AST is structural and has spans, so such a layer need not change the executable representation.

Design aims are fewer ambiguous choices and useful operations per token, not maximal punctuation. Explicit annotations cost tokens but avoid inference surprises and improve diagnostics. `fold` compresses a common pattern without introducing arbitrary implicit behavior. The benchmark suite counts BPE tokens rather than characters and treats full agent cost as a separate research question.

The first optimization round adds local `:=` inference and dependency-driven result inference for expression functions. Parameter types remain explicit; inference cycles request an annotation. `int` is an exact alias for checked i64. The formatter parses independently of checking and therefore preserves omitted annotations. Fused `sum`/`count` expressions bind scalars from captured array descriptors and emit ordinary C loops, with one zip-length check per additional array before iteration. They allocate no intermediate arrays or closures; effectful bodies run in index order.

Pure i64 `fold ... +` and builtin `sum(a)` call `g_sum_i64`. It scans 256-element blocks using unsigned modular addition and an OR guard. For an element x, `(uint64_t)x + 2^31 <= UINT32_MAX` exactly characterizes signed-i32 values; OR combines these tests without control flow in the inner loop. If all elements fit i32 and the incoming accumulator has 2^39 headroom in both directions, every prefix of 256 additions fits i64. The modular sum then has the same result as the checked left fold and can vectorize. On any failed guard, the entire remaining suffix uses checked scalar addition. This limits speculative failed work to one block per reduction. Small tails, arbitrary initial accumulators, overflowing intermediate prefixes, floating-point folds and effectful generator bodies retain their original semantics. Explicit user loops are not pattern-rewritten in this round.

This specialization is intentionally narrow. It does not establish C-speed execution for arbitrary i64 data, general range analysis, or lower total AI generation cost. `benchmarks.reductions` measures both the fast path and wide-integer fallback against checked loops and ordinary C; `benchmarks.agent` counts actual BPE source tokens for implemented syntax.

Value records add named fields, composition and statically resolved methods. The checker first registers all types, validates finite inline layouts, then resolves function and method signatures. Expression result inference is keyed by owner and method name. Private access and shallow receiver mutation restrictions are checked in the declaring method's context. Constructor expressions and method calls retain their resolved declaration on the typed AST.

The backend emits forward struct declarations, dependency-ordered definitions, and function prototypes before bodies. Field names use `m_`, record types `g_record_`, and method functions an owner-length-qualified prefix to avoid name collisions. Ordinary methods take a struct by value; `mut` methods take a hidden pointer captured before evaluating arguments. No reference escapes into source-language values. Receiver snapshots, argument values and checked indices are sequenced explicitly. Arrays of records use contiguous struct storage and the collected heap; nested array fields retain descriptor sharing. LLVM may eliminate value copies or inline calls, but large records can still be expensive. No general C-speed or AI-token improvement follows merely from adding methods.

The optional GUI library keeps its typed signatures in `gui.py`, C ABI in
`gui.h`, Glyph value adapters in `gui_runtime.h`, and macOS implementation in
`gui_macos.m`. Emitting any GUI call adds the adapters and a generated build
marker; only marked translation units link the platform backend. These builds
use Apple Clang and AppKit, while ordinary executables retain the existing
portable toolchain. Backend resources use ARC and per-operation/event autorelease
pools, independent of Glyph's collected heap. The event loop blocks for native
events and returns button IDs to ordinary Glyph control flow. This does not add
general FFI syntax. See [the API and limits](GUI.md).

Backend references: [Zig's packaged toolchain](https://pypi.org/project/ziglang/0.14.1/), [Clang language extensions](https://clang.llvm.org/docs/LanguageExtensions.html), [Clang user manual](https://clang.llvm.org/docs/UsersManual.html). Runtime overflow uses `__builtin_*_overflow`, not reliance on undefined signed overflow or a release-only sanitizer setting.

## File modules

`glyph/modules.py` loads the source graph before type checking. Each file has
its own declaration table and explicit import bindings. The loader rejects
cycles and conflicts, then rewrites top-level symbols, type references, and
local bindings into isolated internal names. Member names stay unchanged. The
existing checker and C emitter operate on the combined program; shared files
retain a single type identity. Tokens retain source paths for diagnostics.

The native compiler implements the same graph and binding rules in Glyph. It
uses shared AST tables with per-module ranges, then rewrites names before its
ordinary type-checking pass. `selfhost/text.gly` is an imported module in the
compiler itself. Both drivers protect every loaded source from output aliases.

## Collection runtime

Both frontends implement the built-in list/map/set type constructors and method
signatures. Generated C uses `collections_runtime.h`: type-erased shared headers
with statically checked element sizes and GC scanning flags. Lists grow
geometrically; maps and sets use open addressing with tombstones. The C emitter
sequences receivers and arguments into typed temporaries before runtime calls.
Snapshots expose ordinary typed arrays and give collection loops stable inputs.
See [collection semantics and costs](COLLECTIONS.md).

## Library abstractions

Before ordinary type checking, both frontends expand explicit generic instantiations, substitute structural types, and check interface constraints against concrete method signatures. The expansion cache bounds code growth and preserves module identity. Tagged unions lower to a discriminant and C union; exhaustive matching checks both payload binding and return coverage. Function values pair code and environment pointers. Closures capture snapshots into collector-scanned environments, and nested function signatures remain statically checked. See [semantics and limits](ABSTRACTIONS.md).

## Optional services

`tcp_runtime.h` adapts POSIX/Winsock TCP with checked, never-reused handles.
`http_runtime.h` uses libcurl with certificate and hostname verification,
request timeouts and bounded response callbacks. `db_runtime.h` wraps SQLite
connections and prepared statements with explicit lifetimes and copied bindings.
Both emitters include these adapters only for referenced service calls and
mark generated C for the corresponding linker libraries. HTTP/SQLite builds
use system development libraries; ordinary console builds retain the existing
bundled toolchain. `serialization_runtime.h` supplies dependency-free CSV and
strict Base64. See [Services](SERVICES.md) for contracts and platform limits.


## Concurrency

`concurrency.py` checks the fully typed, specialized AST. Boundary checks reject
mutable/reference-bearing graphs except immutable strings and explicit channel
capabilities; call-graph traversal with recursion guards checks an explicit
worker builtin allowlist. The native compiler implements the same traversal in
Glyph. Both analyze imported functions, methods and concrete generic instances.
Opaque callbacks/indirect calls are rejected. This is a conservative effect
check, not a general ownership or alias-analysis language.

Both emitters generate typed per-call adapters, with direct native calls for
known map/task functions, around `concurrency_runtime.h`. Numeric maps allocate
one fresh result and schedule chunks through a reusable bounded pthread pool.
Nested maps run locally. Blocking tasks use a separate bounded pthread path;
compiler-generated scope exit code joins outstanding children on every return.
Channels use mutex/condition-variable bounded rings. The scheduler, task and
channel algorithms exist once in the shared C runtime.

The concurrency marker selects GC_THREADS, pthread linking and a distinct cached
collector object. Native builds supply the same flags without Python. Worker
stacks are registered by BDWGC's pthread wrappers. Sequential programs retain
the single-threaded build and do not start threads. Source-location state is
thread-local, fatal diagnostic output is serialized, and unaudited resource
subsystems are excluded by worker effect checks. See [the contract](CONCURRENCY.md)
and [measured results](../benchmarks/results/macos-arm64-2026-10-27-concurrency/REPORT.md).
