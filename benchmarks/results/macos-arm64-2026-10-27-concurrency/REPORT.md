# Concurrency delivery and measurements — 2026-10-27

Implementation and execution host: Apple M2, 8 logical/physical cores as reported
by the host, 8 GiB RAM, macOS 26.5.2 arm64. Zig 0.14.1 / Clang 19.1.7 builds the
benchmark applications at `-O2 -fno-fast-math -ffp-contract=off`, with no LTO,
stripping or CPU-specific tuning. Native compiler generations use Apple Clang.
No claim of cross-platform runtime correctness follows from this run.

## Delivered language and runtime

Both the reference frontend and native Glyph compiler implement:

* `par_map(array, named_function_or_literal_lambda)`: int/f64 input and output,
  fresh nonoverlapping result storage, one evaluation of inputs/captures, joined
  completion, numeric checks, empty inputs and uneven tails. Ordinary reductions
  retain their checked left-to-right order. No parallel reductions were added.
* Lexical `scope`, `t := spawn(callback)`, `task_status(t)` (IntResult), and
  `wait(t)` (typed result). Scopes join on fallthrough and every return, including
  recoverable error returns. Wait is repeatable. Handles are inferred local
  bindings only and cannot be copied, reassigned, returned, captured or stored.
* `channel[T] = channel(capacity)`, `send`, `receive`, and `close`. Buffers have
  positive checked capacity. Send returns false after close; receive returns
  false only when closed and drained, otherwise invokes `fn(T)>void` on the
  receiver after dequeue. Repeated close is harmless and wakes all waiters.
  FIFO is enqueue order; each producer's order is preserved, inter-producer
  ordering is unspecified. Empty payloads remain distinct from closure.

Boundary values are recursively safe scalars, immutable strings and value
records/unions. Tasks additionally accept channel capabilities. Mutable arrays,
collections, reference-bearing aggregates, pointers and function-valued captures
or results are rejected. Worker-local arrays/collections remain usable. Direct
calls, recursive calls, methods, imported functions and generic specializations
are checked transitively; unknown indirect effects are rejected. Snapshot captures
and shallow clones are never treated as proof of isolation. Worker file/network/
database/process/GUI calls and printing are rejected, even with integer handles.
Main-thread service and GUI operations can coexist with concurrency.

A lazy reusable CPU pool uses chunks of at least 256 and a sequential cutoff of
1024 elements. `GLYPH_WORKERS=1..32` includes the main participant; default is
min(CPUs,8). Nested maps and maps inside tasks run serially on their invoking
thread. Blocking tasks use a separate bounded pthread path, default 64 unjoined
native threads (`GLYPH_TASK_LIMIT=1..256`), so CPU-pool saturation cannot starve
channel producers. Spawn exhaustion/creation failures are inspectable through
`task_status`; invalid waits/configuration/capacity report R018. Allocation
failure remains R004 and fatal language traps retain status 70. Concurrent fatal
traps flush the diagnostic and use `_Exit(70)`, avoiding atexit handlers racing
with active main-thread resources; buffered stdout need not flush. Sequential
fatal behavior is unchanged. A test proves that fatal shutdown bypasses a
cleanup handler whose resource is still locked by the main thread.

BDWGC 8.2.12 uses GC_THREADS and collector-aware pthread creation/join only in
concurrent builds. Registered stacks, scanned descriptors/environments/results,
scanned channel rings and blocked sender stacks retain references. Start, joins
and channel locks provide publication; source-location state is thread-local.
Normal completion wakes and joins idle CPU workers. Channel finalizers destroy
synchronization objects only after active references disappear. Collection stays
enabled; allocation-free code can still pause for GC. There is no detached task,
forced cancellation, general shared mutation, public lock/atomic API or async
system. Cyclic application waits can deadlock, and process termination does not
promise cleanup. Joined descriptors remain rooted until their scope exits.

See the [full contract](../../../docs/CONCURRENCY.md) and runnable
[parallel](../../../examples/parallel.gly), [tasks](../../../examples/tasks.gly),
and [channels](../../../examples/channels.gly) examples.

## Validation evidence

The final reference run passes **123 tests, two skips**. The skips are existing
macOS tests requiring `/dev/full`. The final native run also passes **123 tests, 2 skips**, with
1,754 native checks and 115 C emissions. Its three-stage fixed
point is recorded in `verification.json` and `corpus.json` alongside this report.
Native generations execute without Python on PATH. A wheel was built, extracted,
and used by the native compiler to build/run the channel example with no Python
on PATH; see `package-verification.json`.

Concurrency tests cover O0/O2/O3, 1/2/4 workers, empty/tiny/large/uneven maps,
nesting, capture/result lifetime, early returns, repeated joins, unsafe graphs,
handle escape, imports/generics/methods, channel FIFO and multiple producers,
capacity-one handshakes, closure and backpressure, GC stress, worker traps and
resource exhaustion. Test-only C instrumentation uses condition variables to
prove simultaneous callback execution, observes blocked senders/receivers before
closing, collects with payloads reachable solely through blocked stacks/buffers,
injects pthread creation failure, and exercises repeated pool startup/shutdown.
No sleep or speedup is used as the overlap proof. Deadlock-prone cases have
subprocess timeouts. The initial sandbox run's seven existing service-test
failures were local-bind permission errors; the successful rerun had socket
access. Both logs are retained.

UBSan passes the instrumented runtime, including the collector, under GC stress.
ASan fails during initialization; TSan crashes without diagnostics. Crucially,
empty C control programs without Glyph or GC fail identically on this host.
See `sanitizer-controls.json` and the sanitizer logs. These tools provide **no
ASan or race-freedom evidence** here. Stress tests are not a proof of race freedom.

macOS arm64 has execution evidence. Linux x86-64 glibc has cross-compilation
only (`linux-cross-compile.json`). Windows concurrency builds produce G203;
Linux musl is explicitly rejected because this collector configuration depends
on getcontext. The initial musl linker failure and subsequent explicit diagnostic
are preserved separately. Existing sequential platform paths remain available.

## Performance observations

Every case has one warmup and five measured process samples, shuffled with seed
27. Internal first-dispatch time is recorded separately from repeated transforms;
wall time includes process startup/setup/output/shutdown. Fresh result allocation
is included in every transform. No RSS sampling, affinity or thermal controls
were used. Exact commands, sizes, flags, hashes, output checks and individual
samples are in [benchmarks.json](benchmarks.json); application sources and the
runtime snapshot used for measurement are retained here.

C uses the same checked arithmetic, GC allocation and scheduler implementation
as Glyph, with handwritten typed kernels. This is a controlled frontend/lowering
comparison, **not an independently optimized C scheduler**. Sequential C also
uses the same collector. Python uses a persistent ProcessPoolExecutor with
chunksize 256: real CPU parallelism in processes, with serialization and larger
process-startup costs. The first call includes launching those processes.

Median **total milliseconds across the stated passes**:

| Workload | Elements × passes | Glyph sequential | Glyph 1 worker | Glyph 2 workers | Glyph 4 workers | C 4 workers |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| compute | 20,000 × 3 | 13.386 | 13.277 | 6.947 | 3.917 | 3.914 |
| memory | 500,000 × 5 | 1.545 | 3.000 | 2.047 | 1.529 | 1.625 |
| tiny | 32 × 3,000 | 0.164 | 0.229 | 0.239 | 0.230 | 0.223 |
| allocation | 5,000 × 3 | 0.892 | 0.954 | 2.431 | 2.482 | 2.920 |

The numeric recurrence improves **3.42×** over sequential Glyph at four
workers. This is one compute-heavy workload, not linear-scaling or general
C-parity evidence. The bandwidth workload merely catches up with the ordinary
Glyph loop at four workers; its sequential C baseline is faster. Tiny maps take
the sequential path but still pay the threaded allocator/runtime cost. The
allocation-heavy string transform slows down with more workers: collector and
allocation contention dominate this workload.

Additional medians:

* Task creation + join: 19.143 ms per 1,000 tasks
  (19.14 µs/task); C 18.648 ms.
* Channel throughput: 2.035 ms for 20,000 checked messages;
  C 1.303 ms. This includes one producer thread's lifecycle.
* Capacity-one blocking round trips: 2.869 ms for 1,000
  exchanges (2.87 µs/round trip); C 2.772 ms.
* Allocation-only: twenty allocations/fills of 500,000 ints take
  2.967 ms in Glyph, 2.711 ms
  in C. This separates baseline allocation/fill cost from parallel scheduling.
* Python compute steady totals: 297.6,
  154.5, 86.9 ms
  at 1/2/4 processes, versus 3.917 ms for four Glyph
  workers. Different interpreter/process execution costs prevent a general claim.

Against pre-change revision `1cba5385bc3af12966227d9ac5d5679596b708bd` (15 randomized samples,
one warmup), ordinary startup median is 2.878 ms
versus 3.002 ms; binary sizes are
98,048 versus 98,192 bytes.
Sequential bandwidth-kernel median is 1.610 ms
versus 1.604 ms, within ordinary session noise.
The compute example grows from 118,152 bytes sequential to 140,984 bytes parallel.
These are observations, not a statistically established zero-regression guarantee.
See [auxiliary-validation.json](auxiliary-validation.json).

## Source-token observations

Using tiktoken 0.12.0 `cl100k_base`, complete authored compute applications cost
**214 Glyph / 398 C /
210 Python tokens**. Task examples cost
95 Glyph / 188 C; channel examples cost
210 Glyph / 285 C. These include drivers.
The C fixtures import the shared Glyph runtime; its support-token counts are
reported separately in the JSON, rather than pretending these are standalone
C implementations. Runtime implementation tokens are likewise excluded from
Glyph and Python application counts. The observations support a narrow
Python-like source-cost result for these fixtures; they do not measure total
agent cost, repair effort, API familiarity or optimal code golf.

## Reproduction and limitations

```sh
DEVELOPER_DIR=/Library/Developer/CommandLineTools GLYPH_TEST_GUI=1 \
  .venv/bin/python -m unittest discover -s tests -v
DEVELOPER_DIR=/Library/Developer/CommandLineTools GLYPH_TEST_GUI=1 \
  .venv/bin/python selfhost/bootstrap.py --verify --output-dir build/concurrency-final
DEVELOPER_DIR=/Library/Developer/CommandLineTools \
  .venv/bin/python -m benchmarks.concurrency --samples 5
```

Service tests need local socket permission; GUI tests need a desktop session.
The measurement runtime snapshot predates the explicit Linux-musl guard and fatal-trap atexit bypass;
neither affects the successful macOS workloads measured here. The auxiliary validation script
expects the pre-change package archived under `build/concurrency-baseline` and
its startup/bandwidth executables prepared as recorded in the JSON.

Remaining limits are deliberate first-version restrictions: only numeric map
elements, statically known concurrency callbacks, no mutable graph transfer,
no worker I/O/services/GUI, OS-thread cost for each scoped task, GC pauses and
allocation contention, possible application deadlocks, no cancellation, and
no Linux runtime or Windows concurrency verification. ASan/TSan are unavailable
on this host. No general C-speed, universal token parity, linear scaling or
cross-platform correctness claim is made.
