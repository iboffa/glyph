# Collections

Both the reference and self-hosted compilers support three built-in collection
families. They are shared mutable references managed by the garbage collector.

```gly
main>void
  tasks := list(["build", "test"])
  tasks.append("ship")
  print(tasks.get(0))

  scores:map[str,int] = map([], [])
  scores.put("Ada", 42)
  print(scores.get_or("Grace", 0))

  tags := set(["native", "typed", "native"])
  print(len(tags))
  for tag:tags
    print(tag)
```

## Types and construction

| Type | Constructor | Contents |
| --- | --- | --- |
| `list[T]` | `list(array)` | Ordered growable sequence of T |
| `map[K,V]` | `map(keys, values)` | Unique keys associated with values |
| `set[K]` | `set(array)` | Unique keys |

T and V can be `int`/`i64`, `f64`, `bool`, `str`, a record, a tagged union, or a function value. Keys must be
`int`/`i64`, `bool`, or `str`. String keys compare by their UTF-8 bytes, including
embedded NUL bytes. There is no Unicode normalization. Floating-point and record
keys are not supported. These remain built-in type constructors. User-defined generics can accept or return them; see [library abstractions](ABSTRACTIONS.md).
Directly nested collection/array type arguments are not supported; use records
with collection fields to compose them. Recursive collection fields are allowed.

Constructors copy their input array elements; later changes to an input array
do not change the collection. Map input arrays must have equal lengths (R007).
Duplicate map keys retain the last value; duplicate set keys are collapsed.

Nonempty constructors infer their types. An empty constructor requires context:

```gly
numbers:list[int] = list([])
scores:map[str,int] = map([], [])
tags:set[str] = set([])
```

Typed parameters, record fields and explicit result annotations also supply this
context. `numbers := list([])` is ambiguous and rejected. `int` is an exact alias
for `i64` inside collection types as elsewhere.

## Operations

All collection types support `len(c)`, `clone(c)`, and `c.clear()`.

| List method | Result and behavior |
| --- | --- |
| `append(value)` | Appends one element; returns void |
| `get(index)` | Returns an element by value |
| `set(index, value)` | Replaces an element; returns void |
| `pop()` | Removes and returns the last element |
| `remove(index)` | Removes and returns an element, shifting later elements |
| `to_array()` | Returns an independent array snapshot |

List indices are zero-based integers. Invalid indices and popping an empty list
raise R003. Access uses methods; square-bracket indexing and `ptr` remain array
operations. A returned record is a value copy: bind it, edit it, and call `set`
or `put` to replace the stored value. Reference-bearing fields still share their
referents.

| Map method | Result and behavior |
| --- | --- |
| `put(key, value)` | Inserts or replaces a value; returns void |
| `get(key)` | Returns a value; a missing key raises R011 |
| `get_or(key, fallback)` | Returns the stored value or fallback |
| `contains(key)` | Returns whether the key exists |
| `remove(key)` | Returns true if an entry was removed |
| `keys()` | Returns an independent array of keys |
| `values()` | Returns an independent array of values |

`get_or` evaluates its fallback even when the key exists, as with all ordinary
method arguments. Receiver and arguments evaluate once, from left to right;
lookup or mutation occurs after argument evaluation.

| Set method | Result and behavior |
| --- | --- |
| `add(key)` | Returns true if a new key was inserted |
| `contains(key)` | Returns whether the key exists |
| `remove(key)` | Returns true if the key was removed |
| `to_array()` / `keys()` | Returns an independent array of keys |

## Sharing, snapshots and iteration

Assignment, function calls and record copies share a collection's identity:

```gly
a := list([1])
b := a
b.append(2)
print(len(a)) # 2
```

`clone` creates an independent collection with shallow element copies. Nested
arrays and collections inside records remain shared. Clearing one alias clears
all aliases; clearing a clone leaves the original collection intact.

`for x:collection` captures an array snapshot once before the first iteration.
Lists visit elements in list order. Maps visit keys; sets visit their elements.
Map and set order is unspecified and may change after mutation. Mutations during
a loop do not change the captured sequence. Snapshot records copy inline fields
but retain shared reference fields.

`keys()` and `values()` use matching order when called on an unchanged map.
Snapshots remain valid after growth, removal or clearing. Reductions remain array
operations: use `sum(numbers.to_array())` or `sum(scores.values())`.

## Runtime and costs

Lists use geometric capacity growth: append is amortized O(1); get, set and pop
are O(1); removing an interior element is O(n). Maps and sets use open-addressed
hash tables with deletion markers, capacity growth and tombstone rebuilding.
Lookup, insertion and removal are expected O(1) for fixed-size keys, with O(n)
worst cases. String hashing costs O(key bytes). Hashing is deterministic and is
not hardened against adversarial collision inputs.

Construction and cloning copy elements; collection iteration allocates a
snapshot. List snapshots cost O(n); map/set snapshots scan table capacity.
`clear` retains capacity and zeros stored references; it costs O(capacity).
Deleted elements are zeroed so they do not keep referenced objects alive.

Collection headers and backing buffers are GC-owned. Numeric/Boolean data and
pointer-free records use atomic allocations; strings and reference-bearing
records use scanned storage. Cycles are supported. Growing a collection can
replace its internal buffer, but its shared header remains stable and no raw
buffer pointers are exposed. Existing fixed arrays, their aliasing, their stable
pointers and the copying `push(array, value)` operation retain their semantics.
