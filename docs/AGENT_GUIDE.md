Glyph uses UTF-8 `.gly` files and two-space blocks. Functions use typed parameters: `name a:[int]>int` plus an indented body, or `name a:[int] = expression` with inferred result. Use `ret value` in blocks. Entry is `main>void` or `main>int`; `main = 0` also works. Calls use `f(a, b)`. Declare locals with `x := 0` or `x:int = 0`; assign existing variables with `x = 1` or `x += 1`. Types: int (checked i64), f64, bool, str, scalar/record arrays `[T]`, and built-in `list[T]`, `map[K,V]`, `set[K]` collections. No implicit conversions or shadowing. Empty arrays need a type: `a:[int] = []`. Recursive result inference needs an explicit annotation.

Control: `if condition` then block, optional `else` block; `while condition` then block; `for x:array` then block. Comparisons and `and`, `or`, `not` yield Boolean values. Standard numeric precedence applies. Use `print(value)`, `len(a)`, `range(n)`, `fill(n, value)`, `clone(a)`, `push(a, value)`. `fold a 0 +` sums a numeric array in order; `fold a 1 *` multiplies. Parenthesize fold inside other expressions. `i64(x)` and `f64(x)` are explicit conversions. `argi(0)` reads the first integer program argument.

Use `sum(a)` for numeric arrays, `count(flags)` for bool arrays, `count(x > 0 for x in a)`, or `sum(x * y for x, y in zip(a, b))`. These are fused loops, with one iteration clause and no filter clause. Zip requires equal lengths. Sources evaluate once left to right; bodies run in index order. Empty reductions return zero. Existing user functions named sum/count override ordinary calls; generator forms are intrinsic.

Define records with `type Point` and indented `x:f64`, `y:f64` fields; construct with `Point(1.0, 2.0)` and access `p.x`. Fields are required positional arguments in declaration order. Records copy by value, including nested records; array fields still share storage. Arrays can contain records. `clone` copies elements, not nested array allocations. Direct recursive record layouts are forbidden; recursive array fields work.

Declare methods inside a type: `norm2 = self.x * self.x + self.y * self.y`. Call `p.norm2()`. Prefix mutating methods with `mut`, e.g. `mut move dx:f64>void` with body `self.x += dx`. A mut receiver must be a variable, addressable field or array element. Ordinary methods receive a snapshot and cannot replace self or its inline fields, but can update shared array elements. `static origin = Point(0.0, 0.0)` is called as `Point.origin()`. Prefix members with `private` to restrict access to that type's methods; records with private fields need a public static factory for outside construction. No inheritance, runtime interface dispatch, overloads, record equality or record printing.

Integers and indexing trap on overflow/out-of-bounds, including intermediate reduction overflow. Array assignments share storage; clone copies elements. Arrays and dynamic strings are garbage collected without moving. Non-void functions must return on every path. Named file imports and explicit user generics are supported. Use `id[T] x:T>T = x` and `id[int](1)`. Pointer operations require `unsafe` and valid numeric/Boolean array-derived pointers.

Use `glyph check file.gly`, `glyph build file.gly -O2`, `glyph run file.gly -- 10`, `glyph fmt file.gly`. Add `--json` for structured diagnostics. Fix the first error and recheck. Verify outputs before claiming completion.

Text/system builtins: `concat(a,b)`, `slice(s,start,end)` on UTF-8 byte boundaries,
`byte_at(s,i)`, `chr(code)`, `join(parts,count,separator)`, `str_i64`, `str_f64`,
`parse_i64`, `parse_f64`, `valid_f64`, `read_file`, `write_file`, `same_file`,
`argc()`, `arg(i)`, `getenv`, `platform`, `process([executable,args...])`, `eprint`,
and `exit`. Slices retain their backing strings; prefer joining parts over
repeated concatenation. `process` is POSIX-only and uses no shell.

Bootstrap the native compiler with `python selfhost/bootstrap.py --verify`.
Then `build/selfhost/glyphc check|emit-c|build|run source.gly` works without Python;
use `--runtime-dir glyph` (or an absolute path) for emission/builds outside the
repository root. Native `fmt` is not implemented. See `docs/SELF_HOSTING.md`.

Import selected declarations with `import Name, other from "./library.gly"`
before any definitions. Paths are relative to that file. Imported files must
not define `main`; cycles, re-exported imports, and conflicting bindings are
rejected. See [Modules](MODULES.md).

Use `list([1, 2])`, `map(["key"], [42])`, or `set(["tag"])` for growable collections.
Empty forms need context: `a:list[int] = list([])`, `m:map[str,int] = map([], [])`.
Lists have append/get/set/pop/remove/to_array; maps have put/get/get_or/contains/
remove/keys/values; sets have add/contains/remove/to_array. All support len, clone,
and clear. Assignments share mutation; clone is shallow. Keys must be int, bool or
str; list elements and map values may also be f64 or records. `for x:c` visits a
snapshot (map keys, set members); map/set order is unspecified. Use methods for
access, not brackets or ptr. See [collections](COLLECTIONS.md).

Libraries can declare `union Result[T,E]` with named payload variants and exhaustive `match`/`case` blocks. Function types use `fn(int)>int`; closures use `fn(x:int)>int = x + offset` and capture value snapshots (arrays/collections share storage). Declare `interface Named` with a `name>str` signature and constrain `label[T:Named]`; contracts are checked at specialization. See [library abstractions](ABSTRACTIONS.md).

Binary I/O: `try_read_bytes(path)` / `try_write_bytes(path, bytes)` use `[int]` bytes (0..255). Chunk files with `try_open(path, "r"/"w"/"a")`, `try_read(handle, count)`, `try_write(handle, bytes)`, `try_flush(handle)` and `try_close(handle)`. Check `.ok`; close explicitly. `encode_utf8` and `try_decode_utf8` cross the text/binary boundary.

JSON: `try_json_parse(text)` returns validated JSON text. `try_json_get`, `try_json_at`, `try_json_kind`, `try_json_len` and `try_json_keys` navigate it. `try_json_string` decodes a quoted string; `json_quote` encodes ordinary text. Build values with `try_json_array` and `try_json_object`. Check `.ok`; JSON failures use `R012`. See [contracts and limits](SYSTEMS.md#json).

Services: use `try_tcp_*` for blocking byte-stream sockets, `try_http_request` for bounded HTTP/verified HTTPS, and `try_db_*` for SQLite with prepared value bindings. Finalize statements and explicitly close handles. HTTP returns `HttpResult` (`value` body bytes, `status`, `headers` bytes); 4xx/5xx still have `ok=true`. `try_csv_parse`/`try_csv_row` and `csv_row`/`try_csv_write` handle CSV; `try_base64_encode`/`try_base64_decode` handle strict padded Base64. See [signatures, dependencies and limits](SERVICES.md).


Concurrency: use `par_map(a, function)` for independent int/f64 transforms;
use a named function or literal lambda, e.g. `par_map(a, fn(x:int)>int = x*x)`.
Results are fresh arrays; no ordinary reductions change order. Captures cannot
contain arrays, collections, pointers or function values. Use `scope` blocks,
`t := spawn(fn()>int = work(value))`, `task_status(t).ok`, and `wait(t)` for scoped
tasks. Handles cannot be copied/stored/returned; scopes join even on return.

Use `c:channel[str] = channel(2)`, `send(c, text)`, `receive(c, consumer)` and
`close(c)` for bounded communication. Receive returns false only when closed and
drained; its `fn(str)>void` callback runs on the caller. Safe records/unions may
cross task/channel boundaries; channels may be captured by tasks. Handle spawn
failure before waiting on messages a missing child would produce. Workers reject
unsafe code, unknown effects, printing, file/network/database/process and GUI
APIs. Set `GLYPH_WORKERS=1..32` for reproducible maps. See [Concurrency](CONCURRENCY.md)
for task limits, nesting, blocking and shutdown rules and runnable examples.
