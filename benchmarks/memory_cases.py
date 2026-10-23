"""Bounded, output-checkable workloads for experimental memory managers."""

CASES = {
    "numeric": {
        "source": """work seed:int>int
  a := fill(4096, seed)
  b := clone(a)
  b[0] += 1
  ret sum(a) + sum(b)
main>void
  ret
""",
        "expected": lambda n: 8192 * n * (n - 1) // 2 + n,
        "region_eligible": True,
    },
    "text": {
        "source": """work seed:int>int
  s := str_i64(seed)
  i := 0
  while i < 64
    s = concat(s, "abcdefghijklmnop")
    i += 1
  ret len(s) + byte_at(s, len(s) - 1)
main>void
  ret
""",
        "expected": lambda n: sum(len(str(i)) + 1024 + ord("p") for i in range(n)),
        "region_eligible": True,
    },
    "cycles": {
        "source": """type Node
  links:[Node]
  value:int
work seed:int>int
  i := 0
  total := 0
  while i < 64
    a := [Node([], seed)]
    b := [Node(a, i)]
    a[0].links = b
    total += a[0].links[0].links[0].value
    i += 1
  ret total
main>void
  ret
""",
        "expected": lambda n: 64 * n * (n - 1) // 2,
        "region_eligible": True,
    },
    "retained": {
        "source": """type Chunk
  data:[int]
  label:str
setup>[Chunk] = fill(32, Chunk([], ""))
work seed:int, keep:[Chunk]>int
  a := fill(4096, seed)
  text := concat("entry-", str_i64(seed))
  keep[seed % 32] = Chunk(a, slice(text, 6, len(text)))
  ret keep[seed % 32].data[4095]
validate keep:[Chunk]>int
  total := 0
  for chunk:keep
    total += chunk.data[4095] + parse_i64(chunk.label)
  ret total
main>void
  ret
""",
        "expected": lambda n: n * (n - 1) // 2,
        "region_eligible": False,
    },
}

# Used with a full GC before every allocation, at O0/O2/O3. Heap-held
# interior pointers must remain valid after the originating function returns.
STRESS = """type View
  text:str
type Pointer
  value:*int
type Node
  links:[Node]
  value:int
views>[View]
  text := concat("prefix-", "survives-suffix")
  ret [View(slice(text, 7, 15))]
pointer>[Pointer]
  a := fill(64, 73)
  unsafe
    ret [Pointer(offset(ptr(a), 32))]
past>[Pointer]
  a := fill(64, 91)
  unsafe
    ret [Pointer(offset(ptr(a), 64))]
cycle>[Node]
  a := [Node([], 123)]
  b := [Node(a, 456)]
  a[0].links = b
  ret a
noise>void
  i := 0
  while i < 200
    a := fill(2048, i)
    if a[2047] != i
      print("bad")
    i += 1
main>void
  v := views()
  p := pointer()
  end := past()
  c := cycle()
  a := fill(4, 7)
  alias := a
  clone := clone(a)
  alias[0] = 8
  noise()
  print(v[0].text)
  unsafe
    print(load(p[0].value))
    print(load(offset(end[0].value, -1)))
  print(c[0].links[0].links[0].value)
  print(a[0])
  print(clone[0])
"""
STRESS_EXPECTED = "survives\n73\n91\n123\n8\n7\n"
