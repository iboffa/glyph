# Library abstractions

Both the Python frontend and the native self-hosted compiler support explicit
user generics, tagged unions, function values, closures, and interfaces used as
generic constraints. Run [the combined example](../examples/abstractions.gly):

```sh
python -m glyph run examples/abstractions.gly
build/selfhost/glyphc run examples/abstractions.gly
```

## User generics

Put type parameters after a function or record name. Supply all type arguments
explicitly at each use; `int` and `i64` identify the same specialization.

```gly
identity[T] value:T>T = value

type Box[T]
  value:T
  get>T = self.value
  mut put value:T>void
    self.value = value

main>void
  box := Box[str](identity[str]("hello"))
  print(box.get())
```

Parameters substitute through record fields, methods, local declarations,
function signatures, arrays, collections, nested generic types, and other
explicit generic calls. Records retain value-copy semantics; their arrays and
collections still share storage. A generic record's methods use the enclosing
type parameters. Methods do not introduce an additional parameter list.

Each concrete instantiation is checked and compiled to ordinary C functions or
structs. A template body is checked when instantiated, including the operations
it uses on its actual types. There is no type erasure, runtime type argument, or
implicit argument inference. Repeated identical instantiations share code,
including when reached through different imports. Recursive instantiations of
the same signature work; continually growing specializations stop with `G005`.
A compilation permits at most 256 distinct instantiations and 64 nested
expansions. The native compiler also bounds expanded AST, declaration, and
output storage. `void` and unknown types cannot be type arguments, even when a
parameter is otherwise unused.

## Tagged unions and matching

A union is a value with exactly one active named variant. Variants can have
zero or more typed payload fields. Union declarations can be generic.

```gly
union Result[T,E]
  Ok value:T
  Err error:E

read result:Result[int,str]>int
  match result
    case Ok(value)
      ret value
    case Err(message)
      print(message)
      ret -1

main>void
  print(read(Result[int,str].Ok(42)))
```

Construct variants with `Type.Variant(...)`; use `Type.Variant()` for an empty
variant. A `match` evaluates its subject once and copies its active payload into
case-local bindings. Arrays and collections inside a payload still share
storage. Bindings cannot shadow visible variables. Empty cases can be written
as `case None` or `case None()`.

Every match must cover every variant exactly once. Unknown, repeated, and
missing cases produce `G115`; incorrect payload/binding counts produce `G107`.
If every case returns, the match satisfies return-path checking. Cases do not
fall through. Payload fields and the discriminant cannot be accessed directly.
There are no wildcard cases, guards, implicit conversions, or match expressions.

The backend uses a C struct containing a discriminant and a C union of payload
structs. Recursive inline layouts are rejected; arrays or collections provide
indirection for recursive unions. Union arrays are scanned by the collector if
any variant can contain references. Existing built-in `IntResult`,
`FloatResult`, `StringResult`, and `BoolResult` APIs remain compatible; libraries
can define their own generic `Result[T,E]` and adapt those records explicitly.

## Function values and closures

Write a function type as `fn(int,str)>bool`. Function values can be assigned,
passed, returned, stored in records, and placed in arrays or collection values.
A named user function evaluates to a function value:

```gly
increment value:int>int = value + 1
apply callback:fn(int)>int, value:int>int = callback(value)

main>void
  callback:fn(int)>int = increment
  print(apply(callback, 4))
```

A specialized generic function is also a value, e.g.
`callback:fn(int)>int = identity[int]`. Builtins, `main`, and bound methods are
not implicitly converted to function values; wrap a builtin or method in a
lambda when needed.

Lambdas have typed parameters, an explicit result type, and an expression body:

```gly
adder offset:int>fn(int)>int = fn(value:int)>int = offset + value

main>void
  add_ten := adder(10)
  print(add_ten(5))
```

Closures capture only the local values they use, at creation time. Captured
scalars and inline records are snapshots. Reassigning the original variable
does not change the capture. Each invocation receives a local copy of those
snapshots; mutating an inline record through that local copy does not persist
to the next invocation. Captured arrays and collections retain shared storage,
so mutations through those references remain visible. Nested and escaping
closures keep their environments alive through the nonmoving collector; they
do not borrow the creator's stack.

The callee is evaluated before arguments, and arguments remain left to right.
Function signatures must match exactly. Function equality and function-valued
map/set keys are unsupported. Lambda parameters cannot shadow outer bindings.
Lambdas do not inherit an enclosing `unsafe` region. There is no block-bodied
lambda syntax or implicit capture by mutable reference.

The C representation pairs a function pointer with an environment pointer.
Noncapturing function references need no environment allocation. Capturing
lambdas allocate scanned environments. This introduces allocation and indirect
call costs; no performance improvement is claimed.

## Interfaces as generic constraints

An interface lists public instance-method signatures. A concrete record
satisfies it structurally, without an `implements` declaration:

```gly
interface Named
  name>str

type Item
  label:str
  name>str = self.label

label[T:Named] value:T>str = value.name()
```

`label[Item](Item("example"))` checks the contract at specialization time. A
missing, private, static, or incompatible method produces `G114`. Parameter and
result types must match exactly, as must the `mut` receiver qualifier. Inferred
method results are allowed and checked against the required signature.

An interface is a compile-time constraint, not a runtime value type. Calls use
ordinary static record-method dispatch after specialization. This version has
no interface objects, virtual dispatch, interface inheritance, generic
interfaces, associated types, or multiple constraints on one type parameter.
Record inheritance remains deferred.
