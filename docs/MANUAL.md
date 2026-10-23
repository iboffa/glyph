# A little Glyph manual

Glyph is a small, statically typed language that compiles to native programs.
Source files end in `.gly`. Blocks use indentation; use two spaces, never tabs.
Comments start with `#`.

The [systems library](SYSTEMS.md) adds text operations, file access and process
execution. Glyph also has a [native GUI library](GUI.md) and a
[compiler written in Glyph](SELF_HOSTING.md) that can compile its own source.
Arrays and dynamically created strings are garbage collected automatically;
see [memory management](MEMORY.md) for sharing, lifetime and performance details.

## 1. Run your first program

Save this as `hello.gly`:

```gly
main>void
  print("Hello, Igino!")
```

`main` is where execution starts. `>void` means it returns no value.
`print` writes one value followed by a newline.

From the project folder, set up Glyph once (macOS/Linux, Python 3.11+):

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
```

In a new terminal, activate the environment again. Then:

```sh
glyph check hello.gly
glyph run hello.gly
glyph build hello.gly -o build/hello
glyph fmt hello.gly
```

`check` catches syntax and type errors without running anything; success is
silent. `run` compiles and executes. `build` saves an executable that runs without
Python. `fmt` rewrites the file with consistent formatting; add `--check` to
check formatting without changing it.

## 2. Name things and give them types

```gly
main>void
  age := 42
  height:f64 = 1.82
  ready := true
  name := "Igino"
  age += 1
  print(age)
```

Use `:=` to declare a variable and infer its type, or `name:Type = value` to
specify it. Use `=` to change an existing variable. Its type stays fixed.

| Type | Example | Meaning |
|---|---|---|
| `int` or `i64` | `42` | Signed 64-bit integer |
| `f64` | `3.14` | Floating-point number |
| `bool` | `true`, `false` | Boolean |
| `str` | `"hello"` | Immutable UTF-8 string |
| `[int]` | `[1, 2, 3]` | Array of integers |

Numbers do not convert automatically: use `f64(age)` or `i64(height)`.
Integer division truncates toward zero, so `7 / 2` is `3`; `7.0 / 2.0` is `3.5`.
Integer overflow and division by zero stop the program with an error.

## 3. Write functions

```gly
double n:int = n * 2

larger a:int, b:int>int
  if a > b
    ret a
  else
    ret b

main>void
  print(double(5))
  print(larger(3, 8))
```

This prints `10`, then `8`. Read `larger a:int, b:int>int` as “larger takes two
integers and returns an integer.”

Parameters need types. A one-expression function can infer its return type;
a function with an indented body needs `>Type`. Use `ret` to return from a body.
A function returning a value must return on every path. Recursive functions
should have an explicit return type.

## 4. Make decisions and repeat work

```gly
main>void
  for n:range(4)
    if n % 2 == 0
      print(n)
    else
      print("odd")
  remaining := 3
  while remaining > 0
    print(remaining)
    remaining -= 1
```

`range(4)` produces `[0, 1, 2, 3]`. `for n:array` visits each element.
`while` repeats while its condition is true.

Use `==`, `!=`, `<`, `<=`, `>`, `>=` for comparisons and `and`, `or`, `not`
for Boolean logic. Conditions must be Boolean: write `remaining > 0`, not
just `remaining`. For a range test, write `0 < n and n < 10`.

## 5. Work with arrays

```gly
main>void
  numbers := [10, 20, 30]
  numbers[0] = 99
  print(len(numbers))
  print(numbers[0])
  shared := numbers
  shared[1] = 7
  print(numbers[1])
  separate := clone(numbers)
  separate[1] = 8
  print(numbers[1])
  numbers = push(numbers, 40)
  print(len(numbers))
```

This prints `3`, `99`, `7`, `7`, `4`.

Indices start at zero and are checked. Array assignment shares storage:
changing `shared[1]` also changes `numbers[1]`. `clone` creates separate element
storage. `push` returns a new array with an extra element, so assign its result.

Use `fill(5, 0)` for five zeroes. An empty array needs a type:
`numbers:[int] = []`. All elements must have the same type.

For a growing sequence, use a list. Maps associate keys with values, and sets
keep unique keys:

```gly
main>void
  numbers := list([10, 20])
  numbers.append(30)
  print(numbers.get(2))
  scores:map[str,int] = map([], [])
  scores.put("Ada", 42)
  print(scores.get_or("Ada", 0))
  tags := set(["native", "native", "typed"])
  print(len(tags))
```

This prints `30`, `42`, `2`. Collections share mutations on assignment. `clone`
copies a collection; `for x:collection` visits a snapshot (keys for maps).
Map/set order is unspecified. Use `to_array()` on lists and sets, or `keys()`/
`values()` on maps, when an array is needed. See [all collection operations](COLLECTIONS.md).

## 6. Calculate totals and counts

```gly
main>void
  values := [1, -2, 4]
  weights := [4, 5, 6]
  print(sum(values))
  print(count(x > 0 for x in values))
  print(sum(x * y for x, y in zip(values, weights)))
  print(fold values 1 *)
```

This prints `3`, `2`, `18`, `-8`.

`sum` adds numbers; `count` counts true values. The `for ... in ...` form
calculates each contribution without building an intermediate array. Its syntax
differs from a regular `for n:array` loop. Zipped arrays must have equal lengths.
`fold values 1 *` starts at `1` and multiplies by each element in order.

## 7. Group data into records

```gly
type Point
  x:f64
  y:f64
  norm2 = self.x * self.x + self.y * self.y
  mut move dx:f64, dy:f64>void
    self.x += dx
    self.y += dy
  static origin = Point(0.0, 0.0)

main>void
  p := Point(3.0, 4.0)
  q := p
  q.move(1.0, 0.0)
  print(p.norm2())
  print(q.norm2())
  zero := Point.origin()
  print(zero.x)
```

This prints `25`, `32`, `0`.

`type` declares a record. Supply every field in declaration order when
constructing one. Read fields with `p.x`; methods use `self` to access their
receiver. A `mut` method can change the original record. A `static` method is
called on the type, as in `Point.origin()`.

Records copy by value: changing `q.x` leaves `p.x` alone. Array fields still
share their storage when a record is copied. Likewise, a record loop variable
is a copy; use `points[i].move(...)` to change a record stored in an array.

Members are public by default. Mark a field or method `private` to restrict
access to that type's methods. A type with private fields needs a public static
factory for outside construction; see [records.gly](../examples/records.gly).

## 8. Pass input and find mistakes

```gly
main>void
  n := argi(0)
  print(n * 2)
```

Save this as `double.gly`, then run `glyph run double.gly -- 21` to print `42`.
`argi(0)` reads the first program argument as an integer.

Run `glyph check file.gly` before running a program. Errors identify a file,
line, column, and code. Fix the first error and check again. Add `--json` for
machine-readable diagnostics. Runtime failures, such as an invalid index,
also report a source location.

For input or operation failures that your application should handle, use
`try_parse_i64`, `try_parse_f64`, `try_read_file`, `try_write_file` or
`try_process`. Check the returned record's `ok` field, then use `value` on
success or report `message` on failure. You can return the record to a caller
or continue with the next input. See [recoverable failures](SYSTEMS.md#recoverable-failures)
and [the example](../examples/results.gly).

Keep these current limits in mind:

- Names cannot shadow variables already visible in the surrounding scope.
- Strings have no concatenation or slicing; `len` counts UTF-8 bytes.
- `print` accepts individual scalar values; print array elements or record
  fields separately.
- Array allocations stay alive until the program exits. Repeated `push` copies
  the array each time; prefer `fill` and indexed updates when the size is known.
- There is no network I/O or inheritance. User generics, tagged unions, closures, and interface constraints are covered in [library abstractions](ABSTRACTIONS.md).

For more runnable programs, browse [examples](../examples/). For precise rules
and advanced `unsafe` pointer operations, use the [language specification](SPEC.md).

## Splitting a program into files

Write `import square, Counter from "./math.gly"` before your declarations to
use functions or record types defined in another file. The path is relative to
the importing file. Keep `main` in the entry file. See [Modules](MODULES.md)
for examples, visibility, and error rules.
