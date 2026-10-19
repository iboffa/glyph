# Glyph 0.1 language specification

This describes the implemented single-file MVP. Source files are UTF-8 `.gly` files. No preprocessor, imports, macros, implicit conversions, or host-language evaluation exists.

## Syntax

Blocks use spaces and significant indentation; the formatter uses two spaces. Tabs in indentation are errors. Blank lines and `#` comments do not affect parsing. Statements and function headers occupy one physical line. Identifiers are ASCII letters/underscores followed by letters/digits/underscores. Keywords cannot be identifiers. Names are case-sensitive; compiler token names `INDENT`, `DEDENT`, `NEWLINE`, `EOF` are reserved. Functions and variables have separate namespaces. Variables may not shadow a visible variable; disjoint blocks can reuse names.

```text
program  := function+
function := name [name ':' type (',' name ':' type)*] '>' type
            ('=' expression NEWLINE | block)
block    := NEWLINE INDENT statement+ DEDENT
statement := name ':' type '=' expression NEWLINE
           | lvalue ('=' | '+=' | '-=' | '*=' | '/=' | '%=') expression NEWLINE
           | 'ret' [expression] NEWLINE
           | call NEWLINE
           | 'if' expression block ['else' block]
           | 'while' expression block
           | 'for' name ':' expression block
           | 'unsafe' block
type := 'i64' | 'f64' | 'bool' | 'str' | 'void'
      | '[' scalar ']' | '*' ('i64' | 'f64' | 'bool')
scalar := 'i64' | 'f64' | 'bool' | 'str'
lvalue := name | expression '[' expression ']'
```

Expressions are literals, names, arrays `[a, b]`, named calls `f(a, b)`, indexing, parenthesized expressions, unary `-`/`not`, binary operators, and `fold array initial reducer`. The fold's array and initial operands are primary/postfix/unary expressions; parentheses admit arbitrary expressions. Reducer is `+` or `*`. Parenthesize a fold when using it as an operand, e.g. `(fold a 0 +) * 2`.

Precedence, low to high: `or`; `and`; `== !=`; `< <= > >=`; `+ -`; `* / %`; unary; calls/indexing. Binary operators associate left; comparisons are ordinary binary operations, not Python-style chained comparisons. `not x == y` means `(not x) == y`. Comparison operands must match types. Ordering is numeric; equality supports all scalar types. Arithmetic supports matching numeric types; `%` is integer-only. No string arithmetic exists.

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
* `f64`: IEEE binary64 on the supported x86-64 backend. Literals with a decimal point or exponent have this type and must be finite. Runtime arithmetic can produce infinities and NaNs. Native default round-to-nearest behavior is used; no fast-math or fused contraction. Ordered comparisons with NaN are false, `!=` is true. Floating division by zero follows IEEE arithmetic.
* `bool`: `true` or `false`. No truthiness or numeric conversion. `and` and `or` short-circuit.
* `str`: immutable UTF-8 bytes, constructed from JSON-escaped literals. Embedded NUL is supported. Equality compares bytes, without Unicode normalization. `len` counts bytes, not characters. Strings have static lifetime; no concatenation or slicing in this MVP.
* `[T]`: homogeneous mutable array of scalar T, with fixed length and shared identity. Nested arrays are not supported. Index must be i64; every ordinary read/write checks `0 <= index < len`. `for` captures the array descriptor once and visits each element in index order, copying its current scalar value into the loop variable. Changes to later elements are observed. Rebinding the original array variable does not change the iteration's captured descriptor.
* `*T`: typed raw pointer, described below. `void` is only a function return type, never a variable or parameter type.

Every local declaration, parameter and function result has an explicit type. Array literals and loop variables derive their element type from context/array. Empty literals need an expected array type, e.g. `a:[i64] = []`, a function argument or return type. Generic builtin calls do not propagate an expected type into empty literals; bind an explicitly typed empty array first. Variables must be initialized. Parameters are mutable local bindings. Functions are declared program-wide, allow forward calls and recursion, and pass scalar values/array descriptors/pointers by value. Returning a shared array is safe.

There is exactly one `main>i64` or `main>void`, with no parameters. `main` cannot be called. An i64 main result is reduced modulo 256 to form the process exit status; void main exits 0. Non-void functions must return on all statically proven paths. Both arms of an if returning count; loops do not prove a return, even `while true`. Unreachable statements after a proven return are rejected.

All expression operands and call arguments evaluate left to right. Array literal elements evaluate before allocation. Assignment evaluates the target (including index/check), then the right side, then writes. Compound assignment additionally reads the old target value before evaluating the right side. `fold` evaluates its array then initial value once, then reduces left to right. Floating fold is not reassociated. Integer folds and explicit loops have the same checked arithmetic semantics and lower to the same loop operations; error locations may differ.

## Ownership and unsafe code

All arrays belong to one program-lifetime arena. Assignments, calls and returns copy an array descriptor and share its allocation. No automatic deep copying. `clone` explicitly copies. `push` allocates a new array and copies the old contents. Array storage never moves. All arena allocations are released at normal exit and checked runtime failure. There are no exposed free/delete operations, borrowed stack addresses, or pointer casts. This prevents dangling array references in safe code without manual memory management.

The tradeoff is retention: allocations in loops accumulate until exit. `push` is O(n), and repeated push is quadratic. This MVP is unsuitable for long-running, allocation-heavy services without a future scoped-region or reference-counting design. Stack overflow and operating-system termination are not caught runtime diagnostics.

`ptr`, `offset`, `load`, `store` require a lexical `unsafe` block. Pointers can be passed/returned, but dereferencing/arithmetic/construction requires unsafe at each use. Pointer operations are unchecked. Callers must preserve allocation provenance, correct type/alignment and in-bounds access; offset may form at most a one-past pointer, which must not be dereferenced. Violating these requirements has native undefined behavior. Unsafe does **not** disable checks on ordinary integer or array operations. Pointer equality, integer-to-pointer conversion, address-of locals, external FFI and manual deallocation are absent.

## Standard library

| Operation | Semantics |
|---|---|
| `print(value)` | One scalar plus newline; i64 decimal, f64 17 significant digits, lowercase Boolean, str raw UTF-8 bytes |
| `len(array_or_string)>i64` | Array elements or UTF-8 bytes |
| `range(n)>[i64]` | Allocate `[0, ..., n-1]`; n must be nonnegative |
| `fill(n, value)>[T]` | Allocate n copies of scalar value |
| `clone(a)>[T]` | Independent copy of scalar elements |
| `push(a, value)>[T]` | Independent copy with one additional element |
| `fold a init +` / `fold a init *` | Left numeric reduction; empty array returns init |
| `i64(number)` | Identity or truncating float conversion; invalid/nonfinite/out-of-range float traps |
| `f64(number)` | Identity or integer conversion, with possible precision loss |
| `argi(i)>i64` | Parse program argument i, zero-based, excluding executable name; strict signed decimal |
| `clock()>f64` | Monotonic wall seconds with unspecified origin; intended for elapsed time |
| `ptr(a)>*T` | Pointer to numeric/Boolean array storage, unsafe |
| `offset(p, i)>*T` | Pointer plus i elements, unsafe |
| `load(p)>T` | Read pointer, unsafe |
| `store(p, value)>void` | Write pointer, unsafe |

No modules, structs, exceptions, closures, generics in user functions, concurrency, file/network I/O, string builders, dynamic linking interface, or alternate human presentation layer are implemented.

## Diagnostics and formatting

`glyph check/build/run file.gly --json` emits one JSON object per diagnostic to stderr. Frontend stops at the first error; successful checks are silent. Records contain stable `code`, `severity`, `message`, `file`, and `span.start/end` objects. Lines and Unicode code-point columns are one-based; end is exclusive. Nodes point to the relevant token, not necessarily the full expression. EOF spans may be empty. Runtime diagnostics are always JSON and include the operation's line/column; the single source filename is supplied by the executable's generated runtime. Runtime traps exit 70; compiler errors exit 1.

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
| G200 | Filesystem/process error |
| G201 | Backend unavailable |
| G202 | Backend compilation failure |
| G301 | Formatting check failed |
| R001–R006 | Overflow; zero divisor; bounds; allocation; argument parsing; float conversion |

`glyph fmt` parses and prints a canonical AST representation: two-space indentation, standard operator/comma spacing, normalized numeric/string literals, minimal precedence-preserving parentheses, one blank line between functions, final newline. Single return functions become expression bodies when no intervening comment prevents that. Comments are retained in order as standalone comments; trailing comments move above the corresponding statement. Comments between block boundaries may move with the next statement. Formatting does not require type correctness. `--check` reports differences without writing.
