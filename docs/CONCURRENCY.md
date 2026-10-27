# Structured concurrency

Implemented contract (2026-10-27). See [verification status](VERIFICATION.md) for executed evidence.

## API and boundaries

* `par_map(array, function)` returns a fresh numeric array. Input and result
  elements are int or f64. Function is a named function (including an explicit
  generic specialization) or a literal lambda with one element parameter.
  Inputs and captures evaluate once, left to right, before dispatch. Output
  positions correspond to input positions; callback execution order is unspecified.
  Empty input returns an empty array. No existing loop or reduction is parallelized.
* `scope` introduces an indented task scope. `t := spawn(function)` starts a
  zero-argument named function or literal lambda; results must be non-void,
  recursively share-safe values. `task_status(t)` returns IntResult: success
  or a recoverable R018 resource/creation error. `wait(t)` joins and returns the
  typed result; repeated waits return the same value. Waiting on a failed
  spawn traps R018. A scope joins every successfully created child at normal
  fallthrough or return, including returns of recoverable error values. Nested
  scopes join innermost first. A child cannot outlive its scope.
* Handles are inferred local bindings only. They cannot be reassigned, copied,
  passed to user functions, returned, captured, or stored in aggregates.
  Only `wait(t)` and `task_status(t)` consume a direct handle binding.
* `c:channel[T] = channel(capacity)` constructs a positive-capacity bounded FIFO.
  `send(c, value)` blocks for space and returns false after close, true on enqueue.
  `receive(c, callback)` blocks for a message, invokes `fn(T)>void` on the caller
  after removing it, and returns true. Closed and drained returns false without
  invoking the callback. Thus an empty string/zero is never confused with EOF.
  `close(c)` is idempotent, wakes all waiters, and preserves buffered messages.
  Invalid capacity traps R018; allocation failure retains R004.

Share-safe values are numbers, bool, immutable strings, and records/unions whose
fields/payloads are recursively share-safe. Channels are additionally allowed
in task captures/results; channel payloads cannot contain channels. Arrays,
collections, raw pointers, function-valued captures/results and aggregates
containing them cannot cross boundaries. No implicit deep copy exists.
Callbacks must be statically identifiable at the concurrency call site; opaque
function values are rejected. Local arrays/collections allocated inside a worker
are permitted. A conservative transitive effect check follows direct calls,
recursion, methods, imports and concrete generic instances. Unknown indirect
calls, unsafe blocks, resource APIs, process exit, printing and GUI operations
are rejected in workers. Parallel-map callbacks additionally reject tasks and
channels. Numeric input cannot be reachable through a permitted capture, and
fresh output cannot overlap input: there is no in-place map variant.

## Scheduling and memory model

The CPU pool starts lazily, reuses OS threads and claims chunks of at least 256
items. Inputs shorter than 1024 run sequentially; tails use shortened chunks.
`GLYPH_WORKERS=1..32` sets total map participants, including the caller. Default
is min(available CPUs, 8). One-worker mode starts no pool threads. Nested maps
and maps inside tasks execute sequentially on the invoking thread. This bounds
CPU-pool growth and avoids nested pool starvation. Checked arithmetic/indexing
and sequential evaluation inside each callback remain unchanged.

Blocking scoped tasks use a separate, bounded OS-thread path, independent of
CPU workers. `GLYPH_TASK_LIMIT=1..256` defaults to 64 outstanding unjoined native
threads; exhaustion returns a failed task handle. Joins release native resources.
Task callbacks can create nested scopes. This permits channel producers and
consumers to run even when other tasks block. Application cyclic waits and
resource-exhaustion error paths that fail to close channels can still deadlock.
No general deadlock detection, cancellation, detached threads, public locks or
atomics, arbitrary shared mutation, or async/await is provided.

Thread start publishes snapshots; joins publish child results. Channel mutex
unlock/lock publishes enqueued payloads, and condition variables wait in loops.
FIFO is enqueue order under that mutex. Each producer's program order is
preserved; the global order between producers is unspecified. A result survives
scope exit through ordinary value copies and GC roots after joining.

BDWGC 8.2.12 is built with GC_THREADS for concurrent programs. Collector-aware
pthread creation/join registers worker stacks and unregisters completed threads.
Queues, closure environments, task results and channel buffers are scanned GC
allocations; blocked operations retain payloads on registered stacks. Interior
pointers remain supported. GC stress state is initialized before thread start,
source-location state is thread-local, and fatal diagnostics are serialized.
Collection is never disabled. Even allocation-free workers can pause for GC.

Normal program completion joins scopes, wakes idle CPU workers to stop, and
joins the pool. Fatal traps retain exit status 70 and process termination. In concurrent builds
the diagnostic is flushed and `_Exit(70)` bypasses atexit cleanup, which could
race with a main-thread resource operation; buffered stdout is not guaranteed
to flush on a concurrent fatal trap. Sequential traps retain their existing exit
behavior;
cleanup after fatal traps/exit/OS termination is not promised. Channel close
wakes blocked operations; normal shutdown does not cancel user work or interrupt
arbitrary native I/O. Unreachable channel synchronization objects are destroyed
by GC finalizers only after active references disappear.

## Runtime audit and platforms

File/stream, TCP, HTTP/curl, database/statement registries, process spawning,
GUI state, argument/environment access, JSON and serialization adapters are
not worker APIs in this version. The effect allowlist rejects them transitively,
including resource handles encoded as integers. Existing main-thread APIs stay
available. Collection internals need no shared-access locks because only
worker-local graphs are permitted. Immutable text allocation/formatting/parsing
uses local buffers and errno; the process locale is not changed by Glyph.

Concurrent builds target POSIX macOS/Linux (glibc) pthreads. Linux musl is explicitly rejected because
the current bundled-collector configuration requires getcontext. Windows concurrency builds
receive an explicit unsupported-platform error; sequential builds keep their
existing path. Cross-compilation is not execution evidence. Both frontends must
apply the same checks and emit adapters around the shared native runtime.


## Try it

```gly
square x:int>int = x * x
work>str = concat("hello", " task")
show value:str>void
  print(value)

main>void
  print(sum(par_map(range(4096), square)))
  c:channel[str] = channel(1)
  scope
    t := spawn(work)
    if task_status(t).ok
      send(c, wait(t))
    close(c)
    while receive(c, show)
      received := true
```

Run `python -m glyph run examples/parallel.gly`, `examples/tasks.gly`, or
`examples/channels.gly`; the native `glyphc run` accepts the same files.
For a receiving callback that maintains local state on the main thread, create
one closure over a local array/collection and reuse it with `receive`. Such a
closure cannot itself be sent to a task. Main-thread service/GUI calls remain
available in programs that also use concurrency.

The [measurement report](../benchmarks/results/macos-arm64-2026-10-27-concurrency/REPORT.md)
includes the cost of fresh result allocation, tiny dispatches, scoped thread
creation, channel throughput and round trips. Resource limits bound concurrent
native threads; they do not bound application heap usage or work per task.
Joined descriptors remain rooted by their scope until it exits, so place a scope
inside a long-running task-creation loop to release completed descriptors promptly.
