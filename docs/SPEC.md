# Glyph 0.1 language specification

This describes the implemented language. Source files are UTF-8 `.gly` files. Named file imports are described in [Modules](MODULES.md). No preprocessor, macros, implicit conversions, or host-language evaluation exists.

## Syntax

Blocks use spaces and significant indentation; the formatter uses two spaces. Tabs in indentation are errors. Blank lines and `#` comments do not affect parsing. Statements and function headers occupy one physical line. Identifiers are ASCII letters/underscores followed by letters/digits/underscores. Keywords cannot be identifiers. Names are case-sensitive; compiler token names `INDENT`, `DEDENT`, `NEWLINE`, `EOF` are reserved. Functions and variables have separate namespaces. Variables may not shadow a visible variable; disjoint blocks can reuse names.

```text
program  := (function | record | union | interface)+
record   := 'type' name [type_parameters] NEWLINE INDENT member+ DEDENT
member   := ['private'] name ':' type NEWLINE
          | ['private'] ['mut' | 'static'] function
function := name [type_parameters] [name ':' type (',' name ':' type)*] ['>' type]
            ('=' expression NEWLINE | block)
block    := NEWLINE INDENT statement+ DEDENT
statement := name ':' type '=' expression NEWLINE
           | name ':=' expression NEWLINE
           | lvalue ('=' | '+=' | '-=' | '*=' | '/=' | '%=') expression NEWLINE
           | 'ret' [expression] NEWLINE
           | call NEWLINE
           | 'if' expression block ['else' block]
           | 'while' expression block
           | 'for' name ':' expression block
           | 'unsafe' block
type_parameters := '[' name [':' interface_name] (',' name [':' interface_name])* ']'
type := scalar | record_name | union_name | type_parameter | 'void'
      | generic_name '[' type (',' type)* ']' | 'fn(' [type (',' type)*] ')>' type
      | '[' type ']' | '*' ('int' | 'i64' | 'f64' | 'bool')
scalar := 'int' | 'i64' | 'f64' | 'bool' | 'str'
lvalue := name | expression '[' expression ']' | lvalue '.' field_name
```

Expressions are literals, names, arrays `[a, b]`, named calls `f(a, b)`, record construction `Point(x, y)`, field access `p.x`, method calls `p.move(dx, dy)` / `Point.origin()`, indexing, parenthesized expressions, unary `-`/`not`, binary operators, and `fold array initial reducer`. The fold's array and initial operands are primary/postfix/unary expressions; parentheses admit arbitrary expressions. Reducer is `+` or `*`. Parenthesize a fold when using it as an operand, e.g. `(fold a 0 +) * 2`.

An expression-bodied function may omit its result annotation: `total a:[int] = sum(a)`. A block-bodied function still requires `>type`. Local declarations may infer their type with `x := expression`; ordinary `x = expression` only assigns an existing binding.

Fused reductions have the forms `sum(expression for name in array)` and `count(predicate for name in array)`. Multiple names require a matching `zip(array, array, ...)`, e.g. `sum(x * y for x, y in zip(a, b))`. There is exactly one iteration clause, no filter clause or first-class generator value. `in` is contextual in this syntax; ordinary `for` statements still use `for x:a`. `zip` is contextual to a reduction's iterable, not a general function or allocated collection.

Precedence, low to high: `or`; `and`; `== !=`; `< <= > >=`; `+ -`; `* / %`; unary; calls/indexing/field access. Binary operators associate left; comparisons are ordinary binary operations, not Python-style chained comparisons. `not x == y` means `(not x) == y`. Comparison operands must match types. Ordering is numeric; equality supports all scalar types. Arithmetic supports matching numeric types; `%` is integer-only. No string arithmetic exists.

```gly
sum a:[i64]>i64
  s:i64 = 0
  for x:a
    s += x
  ret s

compact a:[i64]>i64 = fold a 0 +

main>void
  print(compact([1, 2, 3]))
```

## Types and values

* `i64`: signed 64-bit integer. Decimal literals, including the special spelling `-9223372036854775808`. Out-of-range literals are rejected. Every addition, subtraction, multiplication, negation, division and remainder checks overflow at every optimization level. Division truncates toward zero; remainder has the dividend's sign. Zero divisor traps. `MIN / -1` and `MIN % -1` both trap.
* `int`: an alias for `i64`, including in `[int]` and `*int`. It is not arbitrary precision. Explicit numeric conversion remains `i64(x)`.
* `f64`: IEEE binary64 on the supported x86-64 and arm64 backends. Literals with a decimal point or exponent have this type and must be finite. Runtime arithmetic can produce infinities and NaNs. Native default round-to-nearest behavior is used; no fast-math or fused contraction. Ordered comparisons with NaN are false, `!=` is true. Floating division by zero follows IEEE arithmetic.
* `bool`: `true` or `false`. No truthiness or numeric conversion. `and` and `or` short-circuit.
* `str`: immutable UTF-8 bytes, constructed from JSON-escaped literals. Embedded NUL is supported. Equality compares bytes, without Unicode normalization. `len` counts bytes, not characters. Literals have static storage; dynamically constructed strings are garbage collected. Text operations and shared-storage slices are described in [the systems API](SYSTEMS.md).
* `[T]`: homogeneous mutable array of scalar, record, union or function T, with fixed length and shared identity. Direct nested arrays are not supported; records can contain arrays. Index must be i64; every ordinary read/write checks `0 <= index < len`. `for` captures the array descriptor once and visits each element in index order, copying its current value into the loop variable. Changes to later elements are observed. Rebinding the original array variable does not change the iteration's captured descriptor.
* User records: nominal value types with inline fields, described below. Two separately declared record types are distinct even when their fields match.
* `*T`: typed raw pointer, described below. `void` is only a function return type, never a variable or parameter type.

Parameters and block-bodied function results have explicit types. A `:=` declaration infers its fixed static type from its initializer, and an expression-bodied function may infer its result. Inference follows forward function and method dependencies; recursive inference cycles require an explicit result annotation (G111). Ambiguous empty literals still require an expected array type, e.g. `a:[i64] = []`, a typed function/constructor argument or explicit return type. Thus `a := []` and `sum([])` are rejected. Generic builtin calls do not propagate an expected type into empty literals; bind an explicitly typed empty array first. No implicit numeric conversions are introduced. Variables must be initialized. Parameters are mutable local bindings. Functions are declared program-wide, allow forward calls and recursion, and pass scalars/records/array descriptors/pointers by value. Returning a shared array is safe.

There is exactly one `main` with no parameters and an explicit or inferred result of i64 or void (e.g. `main = 0`). `main` cannot be called. An i64 main result is reduced modulo 256 to form the process exit status; void main exits 0. Non-void functions must return on all statically proven paths. Both arms of an if returning count; loops do not prove a return, even `while true`. Unreachable statements after a proven return are rejected.

All expression operands and call arguments evaluate left to right. Array literal elements evaluate before allocation. Assignment evaluates the target (including index/check), then the right side, then writes. Compound assignment additionally reads the old target value before evaluating the right side. `fold` evaluates its array then initial value once, then reduces left to right. Floating reductions are not reassociated. Integer folds and explicit loops have the same checked arithmetic semantics; error locations may differ. The compiler may use a guarded fast path for pure array sums when it proves every intermediate prefix safe. A final result fitting i64 does not excuse an overflowing intermediate sum.

Fused reductions evaluate all source arrays once, left to right in the enclosing scope, and capture their descriptors before introducing iteration bindings. Zipped arrays must have equal lengths; R007 is raised after evaluating the sources but before any body evaluation if they differ. Iteration reads all bound elements at each index before evaluating the body once. Mutations to later elements are observed. Bindings cannot shadow visible names and do not escape the reduction. Integer `sum` starts at 0 and checks each left-to-right addition; f64 `sum` starts at 0.0. `count` requires Boolean values and returns the number that are true. Both return zero on empty inputs. Effectful generator bodies retain scalar evaluation order and are not passed to the guarded array-sum helper.

## Value records and methods

```gly
type Point
  x:f64
  y:f64
  norm2 = self.x * self.x + self.y * self.y
  mut move dx:f64, dy:f64>void
    self.x += dx
    self.y += dy
  static origin = Point(0.0, 0.0)

type Particle
  position:Point
  mass:f64

main>void
  p := Particle(Point.origin(), 2.0)
  q := p
  q.position.move(3.0, 4.0)
  print(p.position.norm2())
  print(q.position.norm2())
```

This prints 0 then 25. Assignment, parameters, returns, constructors and array elements copy record fields, recursively including inline records. Array fields copy their descriptors and continue to share storage; record copying is not a deep clone of array allocations. `clone([record])` copies the element records but also shares any arrays inside them. A loop variable is a record copy, so changing its inline fields does not update the array element.

Declare at least one field. Constructor arguments are positional, required, and ordered by field declaration; there are no defaults or constructor bodies. Field and method names must be unique within a type. Types and methods may refer forward. Direct or mutual inline field cycles are rejected (G113); recursive array fields such as `children:[Node]` are allowed because their descriptor has finite size. Type names share the global function namespace and cannot use builtin names, scalar names, `void`, `main`, `sum`, `count`, or `zip`.

Instance methods have implicit `self`. An ordinary method receives a value snapshot and cannot replace `self` or its inline fields. A `mut` method receives access to the original receiver storage and can replace `self`, update fields, and call other mutating methods. Mutation requires an addressable variable, inline field chain or array element: `p.move(...)` and `points[0].move(...)` work, but `Point(0.0, 0.0).move(...)` is rejected. Ordinary methods work on temporary values. A normal method can mutate shared array elements reachable through `self`; its receiver restriction is shallow, not a purity guarantee. Ordinary explicit record parameters remain mutable local copies.

The receiver is evaluated once before arguments. Read methods capture its value before any argument runs; mutating methods capture its storage location before arguments, then see any changes arguments made there. Arguments evaluate left to right. A `static` method has no implicit `self` and is called through the type, e.g. `Point.origin()`. Calling a static method through a value, or an instance method through a type, is rejected. A visible local name takes precedence over a type name in dot-call syntax.

Members are public by default. Prefix a field or method with `private` to restrict access to methods declared on that same type (including access through another instance). If any field is private, positional construction is also restricted to that type's methods; expose a static factory:

```gly
type Counter
  private value:int
  static start = Counter(0)
  get = self.value
  mut add n:int>void
    self.value += n
```

`private`, `mut`, and `static` act as modifiers at the beginning of a member declaration; order is `private` followed by at most one of `mut`/`static`. `type Name` introduces a record at the top level. Methods otherwise use the same signature, return inference and body rules as functions.

Records compile to C structs; methods compile to statically resolved functions. A record value needs no separate heap allocation, object header or virtual dispatch. Arrays containing references are scanned by the collector; arrays of recursively pointer-free records are not. Large value copies and shared array storage still have costs. There is no inheritance, subtyping, runtime interface dispatch, method overloading, user-defined operator, record equality, record printing or raw pointer to a record in this version.

## Generics, unions, function values, and interfaces

[Library abstractions](ABSTRACTIONS.md) specifies the syntax and semantics of
`identity[T]`, `Box[T]`, `union Result[T,E]`, exhaustive `match`/`case` statements,
function types (`fn(int)>int`), expression lambdas (`fn(x:int)>int = x + offset`),
and interface constraints (`label[T:Named]`). These constructs work in both
compilers and through named imports. Generic arguments are explicit; interfaces
constrain specialization without runtime dispatch. Captures are snapshots with
existing shared array/collection semantics. Arrays and collection values can
also contain function values; keys remain limited to int, bool, and str.

## Ownership and unsafe code

Arrays and dynamic strings use automatic, nonmoving tracing garbage collection (BDWGC). Assignments, calls and returns copy an array descriptor and share its allocation. No automatic deep copying. `clone` explicitly copies the elements, including inline record fields but not allocations referenced by those fields. `push` allocates a new array and copies the old contents. Array storage never moves. Unreachable allocations, including cycles, are eligible for collection during execution. Collection timing is unspecified; conservative scanning may retain some unreachable storage. A live slice or interior pointer keeps its whole backing allocation alive. There are no exposed free/delete operations, escaping borrowed stack addresses, or pointer casts. Hidden mut-method receiver pointers cannot be returned or stored by user code. This prevents dangling array references in safe code without manual memory management.

The tradeoffs are collection pauses, conservative retention and allocator overhead. `push` is O(n), and repeated push is quadratic. Collection removes mandatory retention until exit but does not guarantee bounded memory for arbitrary programs or hard real-time latency. See [memory management](MEMORY.md). Stack overflow and operating-system termination are not caught runtime diagnostics.

`ptr`, `offset`, `load`, `store` require a lexical `unsafe` block. Pointers can be passed/returned, but dereferencing/arithmetic/construction requires unsafe at each use. Pointer operations are unchecked. Callers must preserve allocation provenance, correct type/alignment and in-bounds access; offset may form at most a one-past pointer, which must not be dereferenced. Violating these requirements has native undefined behavior. Unsafe does **not** disable checks on ordinary integer or array operations. Pointer equality, integer-to-pointer conversion, address-of locals, external FFI and manual deallocation are absent.

## Standard library

| Operation | Semantics |
|---|---|
| `print(value)` | One scalar plus newline; i64 decimal, f64 17 significant digits, lowercase Boolean, str raw UTF-8 bytes |
| `len(array_or_string)>i64` | Array elements or UTF-8 bytes |
| `range(n)>[i64]` | Allocate `[0, ..., n-1]`; n must be nonnegative |
| `fill(n, value)>[T]` | Allocate n copies of a scalar or record value |
| `clone(a)>[T]` | Independent copy of elements; record array fields still share their allocations |
| `push(a, value)>[T]` | Independent copy with one additional element |
| `fold a init +` / `fold a init *` | Left numeric reduction; empty array returns init |
| `sum(a)` | Checked ordered sum of an i64 or f64 array; empty returns typed zero |
| `count(a)` | Number of true values in a bool array; empty returns 0 |
| `sum(expr for x in a)` | Fused numeric map/reduction with no intermediate array |
| `count(predicate for x in a)` | Fused Boolean map/count with no intermediate array |
| `sum(expr for x, y in zip(a, b))` | Fused reduction over equal-length arrays; also supported by count |
| `i64(number)` | Identity or truncating float conversion; invalid/nonfinite/out-of-range float traps |
| `f64(number)` | Identity or integer conversion, with possible precision loss |
| `argi(i)>i64` | Parse program argument i, zero-based, excluding executable name; strict signed decimal |
| `clock()>f64` | Monotonic wall seconds with unspecified origin; intended for elapsed time |
| `ptr(a)>*T` | Pointer to numeric/Boolean array storage, unsafe |
| `offset(p, i)>*T` | Pointer plus i elements, unsafe |
| `load(p)>T` | Read pointer, unsafe |
| `store(p, value)>void` | Write pointer, unsafe |
| `gui_window`, `gui_label`, `gui_button`, `gui_text`, `gui_number`, `gui_next`, `gui_close` | Optional native GUI library; signatures and lifecycle are specified in [GUI.md](GUI.md) |
| `concat`, `slice`, `byte_at`, `chr`, `join`, `str_i64`, `str_f64`, `parse_i64`, `parse_f64`, `valid_f64` | Text operations; signatures, UTF-8 boundaries and allocation rules are specified in [SYSTEMS.md](SYSTEMS.md) |
| `read_file`, `write_file`, `same_file`, `file_exists`, `arg`, `argc`, `getenv`, `platform`, `process`, `eprint`, `exit` | File/argument/process operations; contracts and platform limits are specified in [SYSTEMS.md](SYSTEMS.md) |

No package manager, import aliases, inheritance, runtime interface objects, exceptions, concurrency, network I/O, mutable string builders, dynamic linking interface, or alternate human presentation layer are implemented.

Recoverable systems-library failures use `IntResult`, `FloatResult`,
`StringResult` and `BoolResult`, reserved built-in value record types with
`ok`, `value`, `code` and `message` fields. The `try_parse_i64`, `try_parse_f64`,
`try_read_file`, `try_write_file` and `try_process` builtins return these records
without terminating on input or operation errors. Applications can construct
and return result records to report their own errors. These follow ordinary
record semantics, with explicit checks and returns; they do not provide
exceptions or automatic propagation. See [contracts and examples](SYSTEMS.md#recoverable-failures).

For compatibility with existing programs, user functions named `sum` or `count` take precedence for ordinary calls. Their generator-expression forms always denote intrinsic reductions. Existing other builtin names remain reserved.

## Diagnostics and formatting

`glyph check/build/run file.gly --json` emits one JSON object per diagnostic to stderr. Frontend stops at the first error; successful checks are silent. Records contain stable `code`, `severity`, `message`, `file`, and `span.start/end` objects. Lines and Unicode code-point columns are one-based; end is exclusive. Nodes point to the relevant token, not necessarily the full expression. EOF spans may be empty. Runtime diagnostics are always JSON and include the operation's line/column; the originating source filename is supplied by the executable's generated runtime. Runtime traps exit 70; compiler errors exit 1.

| Code | Meaning |
|---|---|
| G001 | Lexical/indentation/string error |
| G002 | Grammar error |
| G003 | Unsupported type |
| G004 | CLI source/path/argument contract |
| G005 | Frontend resource/nesting/literal limit |
| G101 | Unknown name |
| G102 | Type mismatch/invalid operation |
| G103 | Duplicate/reserved name or shadowing |
| G104 | Invalid assignment/call/expression statement |
| G105 | Out-of-range literal |
| G106 | Missing return path |
| G107 | Wrong argument count |
| G108 | Invalid/missing entry point |
| G109 | Unreachable statement |
| G110 | Missing unsafe region |
| G111 | Recursive result inference needs an annotation |
| G112 | Private member access or mutation through an ordinary method's self |
| G113 | Recursive inline record/union layout |
| G114 | Unsatisfied interface constraint |
| G115 | Unknown, duplicate, or missing match case |
| G200 | Filesystem/process error |
| G201 | Backend unavailable |
| G202 | Backend compilation failure |
| G203 | GUI backend unavailable on this platform |
| G301 | Formatting check failed |
| G400 | Import path or module resolution error |
| G401 | Missing/conflicting import binding or main in an imported module |
| G402 | Circular import |
| R001–R007 | Overflow; zero divisor; bounds; allocation; argument parsing; float conversion; zip/map length mismatch |
| R008 | Invalid GUI lifecycle, widget ID, dimensions, rectangle or text |
| R009 | Invalid text, Unicode, parsing or C-string conversion contract |
| R010 | File/process failure or unavailable process backend |
| R011 | Missing map key |

`glyph fmt` parses and prints a canonical AST representation: two-space indentation, standard operator/comma spacing, normalized numeric/string literals, minimal precedence-preserving parentheses, one blank line between functions, final newline. Single return functions become expression bodies when no intervening comment prevents that. Comments are retained in order as standalone comments; trailing comments move above the corresponding statement. Comments between block boundaries may move with the next statement. Formatting does not require type correctness. `--check` reports differences without writing.

Formatting preserves `int` versus `i64`, `:=` declarations, and omitted expression-result annotations; it does not expand inferred types back into source.

## Built-in collections

`list[T]`, `map[K,V]` and `set[K]` are shared mutable GC-managed references.
T/V may be scalars, records, unions or functions; K is int/i64, bool or str. Constructors are
`list(array)`, `map(keys, values)` and `set(array)`. Empty constructors use an
expected collection type. Map inputs require equal lengths (R007); duplicate
keys retain the last value. String keys compare by bytes.

`len` and `clone` accept collections. List methods are append/get/set/pop/remove/
to_array/clear; map methods are put/get/get_or/contains/remove/keys/values/clear;
set methods are add/contains/remove/keys/to_array/clear. Missing map get raises
R011; invalid list indices and empty pop raise R003. Method arguments evaluate
left to right, including eager get_or defaults. Element reads copy values.
Collection access uses methods, not array indexing or unsafe pointers.

`for` over a collection captures a shallow array snapshot before iteration.
Maps iterate keys, sets iterate elements, and their order is unspecified. List
order is preserved. Clone and snapshots copy elements but share any nested
references. Collection fields permit recursive record graphs. Directly nested
collection type arguments remain unsupported. User generics and function-valued
collection elements are described in [library abstractions](ABSTRACTIONS.md).
The full method signatures, examples and cost model are in [Collections](COLLECTIONS.md).

Binary and JSON standard-library calls are specified in [the systems API](SYSTEMS.md#binary-and-streaming-io). `BytesResult` and `StringsResult` extend the ordinary result-record convention with `[int]` and `[str]` payloads. Binary files do not require UTF-8. JSON values remain ordinary strings; invalid JSON or lookup failures return `R011`. Both compilers expose identical signatures.
