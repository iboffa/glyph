"""Library abstraction semantics and reference/native compiler parity."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.formatter import format_source
from glyph.modules import load_program
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, ROOT, native, execute


class AbstractionTests(unittest.TestCase):
    def run_source(self, source, name, expected):
        formatted = format_source(source)
        self.assertEqual(format_source(formatted), formatted)
        exe = native(formatted, 'abstractions_' + name)
        with patch.dict(os.environ, GLYPH_GC_STRESS='1'):
            result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)

    def test_generic_records_functions_recursion_and_collections(self):
        self.run_source('''type Box[T]
  private value:T
  static make x:T>Box[T] = Box[T](x)
  get>T = self.value
  mut put x:T>void
    self.value = x
identity[T] value:T>T = value
first[T] items:list[T]>T = items.get(0)
repeat[T] value:T, n:int>T
  if n == 0
    ret value
  ret repeat[T](value, n - 1)
main>void
  a := Box[int].make(7)
  b := a
  b.put(9)
  print(a.get())
  print(b.get())
  nested := Box[Box[str]].make(Box[str].make("nested"))
  print(nested.get().get())
  print(identity[str]("hello"))
  print(first[int](list([21, 22])))
  print(repeat[bool](true, 12))
  f:fn(int)>int = identity[int]
  print(f(34))
''', 'generics', '7\n9\nnested\nhello\n21\ntrue\n34\n')

    def test_tagged_unions_exhaustiveness_and_recursive_arrays(self):
        self.run_source('''union Result[T,E]
  Ok value:T
  Err error:E
union Tree
  Leaf value:int
  Branch children:[Tree]
read result:Result[int,str]>int
  match result
    case Ok(value)
      ret value
    case Err(error)
      print(error)
      ret -1
total tree:Tree>int
  match tree
    case Leaf(value)
      ret value
    case Branch(children)
      result := 0
      for child:children
        result += total(child)
      ret result
main>void
  print(read(Result[int,str].Ok(42)))
  print(read(Result[int,str].Err("failed")))
  tree := Tree.Branch([Tree.Leaf(4), Tree.Leaf(5)])
  print(total(tree))
  values := list([Result[int,str].Ok(8)])
  print(read(values.get(0)))
''', 'unions', '42\nfailed\n-1\n9\n8\n')

    def test_closures_escape_nested_capture_and_function_fields(self):
        self.run_source('''type Callback
  apply:fn(int)>int
add a:int, b:int>int = a + b
make offset:int>fn(int)>int = fn(x:int)>int = x + offset
nested a:int>fn(int)>fn(int)>int = fn(b:int)>fn(int)>int = fn(c:int)>int = a + b + c
apply callback:fn(int)>int, value:int>int = callback(value)
main>void
  f := make(10)
  print(apply(f, 3))
  offset := 4
  snapshot := fn(x:int)>int = offset + x
  offset = 99
  print(snapshot(2))
  plus:fn(int,int)>int = add
  print(plus(2, 8))
  box := Callback(f)
  print(box.apply(5))
  print(nested(1)(2)(3))
  data := [7]
  shared := fn(x:int)>int = data[0] + x
  data[0] = 8
  print(shared(2))
  print((fn(x:int)>int = x * 2)(9))
  print(make(100)(4))
''', 'closures', '13\n6\n10\n15\n6\n10\n18\n104\n')

    def test_interface_constraints_and_mutation(self):
        self.run_source('''interface Named
  name>str
interface Incrementable
  mut increment delta:int>void
type Counter
  value:int
  name>str = str_i64(self.value)
  mut increment delta:int>void
    self.value += delta
label[T:Named] value:T>str = value.name()
advance[T:Incrementable] value:T>T
  value.increment(5)
  ret value
main>void
  original := Counter(3)
  print(label[Counter](advance[Counter](original)))
  print(original.value)
''', 'interfaces', '8\n3\n')

    def test_modules_share_specializations_and_preserve_private_helpers(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            root = Path(directory)
            (root / 'lib.gly').write_text('''interface Named
  name>str
union Maybe[T]
  None
  Some value:T
helper x:int>int = x + 1
at[T] values:[T], T:int>T = values[T]
make[T:Named] x:T>Maybe[str] = Maybe[str].Some(x.name())
closure n:int>fn(int)>int = fn(x:int)>int = helper(x) + n
''')
            entry = root / 'main.gly'
            entry.write_text('''import Maybe, make, closure, at from "./lib.gly"
type Item
  name>str = "imported"
  value:int
main>void
  result := make[Item](Item(0))
  match result
    case None
      print("none")
    case Some(value)
      print(value)
  print(closure(3)(8))
  print(at[int]([9, 8], 1))
''')
            c = root / 'program.c'
            c.write_text(Emitter().emit(check(load_program(entry))))
            exe = root / 'program'
            compile_c(c, exe)
            result = execute(exe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'imported\n12\n8\n')

    def test_callback_containers_gc_and_multi_parameter_function_values(self):
        self.run_source('''choose[A,B] a:A, b:B>A = a
identity[T] value:T>T = value
make prefix:str>fn(int)>str = fn(value:int)>str = concat(prefix, str_i64(value))
main>void
  f:fn(int,str)>int = choose[int,str]
  print(f(12, "unused"))
  callbacks:list[fn(int)>str] = list([])
  for i:range(20)
    callbacks.append(make(concat(str_i64(i), ":")))
  for i:range(1000)
    discarded := concat("temporary", str_i64(i))
  print(callbacks.get(3)(7))
  array := callbacks.to_array()
  index := 8
  print(array[index](2))
  indices := [4]
  print(array[indices[0]](6))
  plus := fn(x:int)>int = x + 1
  copied := identity[fn(int)>int](plus)
  print(copied(9))
''', 'callback_containers', '12\n3:7\n8:2\n4:6\n10\n')

    def test_callee_argument_order_and_contextual_fn_name(self):
        self.run_source('''mark log:list[int], value:int>int
  log.append(value)
  ret value
factory log:list[int]>fn(int,int)>int
  log.append(1)
  ret fn(a:int,b:int)>int = a + b
call fn:fn(int)>int, x:int>int = fn(x)
main>void
  log := list([0])
  print(factory(log)(mark(log, 2), mark(log, 3)))
  for value:log
    print(value)
  print(call(fn(x:int)>int = x + 4, 7))
''', 'order', '5\n0\n1\n2\n3\n11\n')

    def test_invalid_programs(self):
        cases = [
            ('union U\n  A value:int\nmain>void\n  u := U.A(1)\n  print(u._tag)\n', 'G101'),
            ('union U\n  A\n  B\nf x:U>int\n  match x\n    case A\n      ret 1\n    case B\n      print(2)\nmain = 0\n', 'G106'),
            ('unused[T]>int = 0\nmain = unused[Missing]()\n', 'G003'),
            ('interface I\n  f x:int, x:int>int\nmain = 0\n', 'G103'),
            ('interface print\n  f>int\nmain = 0\n', 'G103'),
            ('id[T] x:T>T = x\nmain = id(1)\n', 'G003'),
            ('id[T] x:T>T = x\nmain = id[int,str](1)\n', 'G107'),
            ('id[T] x:T>T = x\nmain = id[int](true)\n', 'G102'),
            ('id[T,T] x:T>T = x\nmain = 0\n', 'G103'),
            ('id[T:Missing] x:T>T = x\nmain = 0\n', 'G003'),
            ('main>void\n  f:fn(void)>int = fn(x:void)>int = 0\n', 'G003'),
            ('main>void\n  x := 1\n  f := fn(x:int)>int = x\n', 'G103'),
            ('main>void\n  f := fn(x:int)>int = true\n', 'G102'),
            ('main>void\n  f := fn(x:int)>int = x\n  print(f(true))\n', 'G102'),
            ('main>void\n  f := fn(x:int)>int = x\n  print(f())\n', 'G107'),
            ('main>void\n  f := 1\n  f()\n', 'G102'),
            ('union U\n  A value:int\n  B\nmain>void\n  u := U.A(1)\n  match u\n    case A(x)\n      print(x)\n', 'G115'),
            ('union U\n  A\nmain>void\n  match U.A()\n    case A\n      print(1)\n    case A\n      print(2)\n', 'G115'),
            ('union U\n  A value:int\nmain>void\n  match U.A(1)\n    case A\n      print(1)\n', 'G107'),
            ('union U\n  A value:int\nmain>void\n  x := U.A(true)\n', 'G102'),
            ('union U\n  A\nmain>void\n  x := U()\n', 'G104'),
            ('union U\n  A value:U\nmain = 0\n', 'G113'),
            ('interface Named\n  name>str\nf[T:Named] x:T>str = x.name()\nmain>void\n  print(f[int](1))\n', 'G114'),
            ('interface Named\n  name>str\ntype Item\n  value:int\n  private name>str = "x"\nf[T:Named] x:T>str = x.name()\nmain>void\n  print(f[Item](Item(1)))\n', 'G114'),
            ('grow[T] x:T>int = grow[Box[T]](Box[T](x))\ntype Box[T]\n  value:T\nmain = grow[int](1)\n', 'G005'),
        ]
        for source, code in cases:
            with self.subTest(source=source):
                with self.assertRaises(Diagnostic) as caught:
                    check(parse(source))
                self.assertEqual(caught.exception.code, code)
