"""Collection semantics, type safety, hash growth/deletion and native parity."""
import json
import os
import random
import unittest
from unittest.mock import patch

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.formatter import format_source
from glyph.modules import load_program
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, native, execute


class CollectionTests(unittest.TestCase):
    def run_source(self, source, name, expected, stress=False):
        exe = native(source, 'collections_' + name)
        with patch.dict(os.environ, GLYPH_GC_STRESS='1' if stress else '0'):
            result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, expected)

    def test_list_alias_copy_and_snapshots(self):
        self.run_source('''grow a:list[int]>void
  for i:range(1000)
    a.append(i)
main>void
  original := [10, 20, 30]
  a := list(original)
  original[0] = 99
  alias := a
  alias.set(1, 21)
  b := clone(a)
  snapshot := a.to_array()
  grow(alias)
  print(a.get(0))
  print(a.get(1))
  print(len(a))
  print(a.pop())
  print(a.remove(0))
  print(a.get(0))
  print(len(b))
  print(snapshot[0])
  a.clear()
  print(len(alias))
  alias.append(42)
  print(a.get(0))
  for value:b
    b.clear()
    print(value)
''', 'lists', '10\n21\n1003\n999\n10\n21\n3\n10\n0\n42\n10\n21\n30\n')

    def test_maps_sets_and_string_keys(self):
        self.run_source('''main>void
  m := map(["a", "b", "a"], [1, 2, 3])
  alias := m
  print(len(m))
  print(m.get("a"))
  alias.put(concat("", "b"), 20)
  print(m.get("b"))
  print(m.get_or("absent", 7))
  print(m.contains("absent"))
  b := clone(m)
  print(m.remove("a"))
  print(m.remove("a"))
  print(b.get("a"))
  print(sum(b.values()))
  for key:m
    m.clear()
    print(key)
  print(len(alias))
  m.put("é\\u0000x", 91)
  print(m.get(concat("é", "\\u0000x")))
  flags := set([true, false, true])
  print(len(flags))
  print(flags.add(false))
  print(flags.remove(true))
  print(flags.add(true))
  copied := clone(flags)
  flags.clear()
  print(copied.contains(true))
  print(len(copied.to_array()))
  print(len(flags.keys()))
''', 'maps_sets', '2\n3\n20\n7\nfalse\ntrue\nfalse\n3\n23\nb\n0\n91\n2\nfalse\ntrue\ntrue\ntrue\n2\n0\n')

    def test_differential_hash_churn(self):
        rng = random.Random(8729)
        mapping, members, lines, output = {}, set(), [
            'main>void', '  m:map[int,int] = map([], [])', '  s:set[int] = set([])'], []
        for i in range(600):
            key = rng.randrange(-120, 120)
            if i % 3:
                value = rng.randrange(-10000, 10000)
                lines += [f'  m.put({key}, {value})', f'  print(s.add({key}))']
                output.append(str(key not in members).lower())
                members.add(key)
                mapping[key] = value
            else:
                lines += [f'  print(m.remove({key}))', f'  print(s.remove({key}))']
                output += [str(key in mapping).lower(), str(key in members).lower()]
                mapping.pop(key, None)
                members.discard(key)
            lines += [f'  print(m.get_or({key}, -1))', '  print(len(m))', '  print(len(s))']
            output += [str(mapping.get(key, -1)), str(len(mapping)), str(len(members))]
        lines += ['  print(sum(m.values()))', '  print(sum(s.to_array()))']
        output += [str(sum(mapping.values())), str(sum(members))]
        self.run_source('\n'.join(lines) + '\n', 'churn', '\n'.join(output) + '\n')

    def test_gc_records_recursive_collections_and_value_copies(self):
        source = '''type Node
  label:str
  children:list[Node]
type Box
  values:list[int]
main>void
  empty:list[Node] = list([])
  root := Node(concat("ro", "ot"), empty)
  empty.append(root)
  nodes := list([root])
  table:map[str,Node] = map([], [])
  for i:range(80)
    table.put(str_i64(i), Node(concat("node-", str_i64(i)), list([])))
    nodes.append(Node(str_i64(i), list([])))
  print(nodes.get(0).children.get(0).label)
  print(table.get("79").label)
  value := table.get("79")
  value.label = "changed"
  print(table.get("79").label)
  print(nodes.pop().label)
  print(nodes.remove(1).label)
  boxes := list([Box(list([42]))])
  other := clone(boxes)
  other.get(0).values.append(7)
  print(len(boxes.get(0).values))
'''
        for optimization in ('0', '2', '3'):
            BUILD.mkdir(parents=True, exist_ok=True)
            c = BUILD / ('collections_gc_O' + optimization + '.c')
            c.write_text(Emitter().emit(check(parse(source))))
            exe = c.with_suffix('.exe' if os.name == 'nt' else '')
            compile_c(c, exe, optimization)
            with patch.dict(os.environ, GLYPH_GC_STRESS='1'):
                result = execute(exe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, 'root\nnode-79\nnode-79\n79\n0\n2\n')

    def test_argument_evaluation_order(self):
        self.run_source('''receiver a:list[int]>list[int]
  print(1)
  ret a
argument a:list[int]>int
  print(2)
  a.clear()
  ret 42
fallback>int
  print(3)
  ret 9
main>void
  a := list([7])
  receiver(a).append(argument(a))
  print(a.get(0))
  m := map(["x"], [8])
  print(m.get_or("x", fallback()))
''', 'order', '1\n2\n42\n3\n8\n')

    def test_empty_types_format_and_inference(self):
        source = '''make>map[str,int] = map([], [])
take a:list[f64]>int = len(a)
main>void
  a:list[int] = list([])
  b:set[str] = set([])
  print(len(make()))
  print(take(list([])))
  print(len(b))
  print(len(a.to_array()))
'''
        formatted = format_source(source)
        self.assertEqual(format_source(formatted), formatted)
        self.run_source(formatted, 'empty', '0\n0\n0\n0\n')

    def test_runtime_traps(self):
        cases = [('list([1]).get(-1)', 'R003'), ('list([1]).get(1)', 'R003'),
                 ('list([1]).set(1, 3)', 'R003'), ('list([1]).remove(1)', 'R003'),
                 ('list(range(0)).pop()', 'R003'), ('map([1], [2]).get(3)', 'R011'),
                 ('map([1, 2], [3])', 'R007')]
        for i, (call, code) in enumerate(cases):
            with self.subTest(call=call):
                result = execute(native('main>void\n  ' + call + '\n', f'collections_trap_{i}'))
                self.assertEqual(result.returncode, 70, result.stderr)
                self.assertEqual(json.loads(result.stderr)['code'], code)

    def test_type_rejections(self):
        cases = [('x := list([])', 'G102'), ('x := map([], [])', 'G102'),
                 ('x := set([1.0])', 'G102'), ('x := map([1.0], [1])', 'G102'),
                 ('x:list[void] = list([])', 'G003'), ('x:set[f64] = set([])', 'G003'),
                 ('x := list(1)', 'G102'), ('x := map([1])', 'G107'),
                 ('list([1]).append(true)', 'G102'), ('list([1]).append()', 'G107'),
                 ('list([1]).unknown()', 'G101'), ('set([1]).get(1)', 'G101'),
                 ('map([1], [2]).put(1, true)', 'G102'), ('map([1], [2]).get("x")', 'G102'),
                 ('map([1], [2]).get_or(1, false)', 'G102'), ('print(list([1]))', 'G102'),
                 ('x := [list([1])]', 'G102'), ('x := list([1]) == list([1])', 'G102'),
                 ('unsafe\n    p := ptr(list([1]))', 'G102')]
        for body, code in cases:
            with self.subTest(body=body):
                with self.assertRaises(Diagnostic) as caught:
                    check(parse('main>void\n  ' + body + '\n'))
                self.assertEqual(caught.exception.code, code)

    def test_imported_record_collection_parameters(self):
        folder = BUILD / 'collection_modules'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'lib.gly').write_text('''type Item
  value:int
make>list[Item] = list([Item(42)])
lookup values:map[str,Item]>int = values.get("x").value
''')
        entry = folder / 'main.gly'
        entry.write_text('''import Item, make, lookup from "./lib.gly"
main>void
  items:list[Item] = make()
  print(items.get(0).value)
  values:map[str,Item] = map(["x"], [Item(7)])
  print(lookup(values))
''')
        c = folder / 'main.c'
        c.write_text(Emitter().emit(check(load_program(entry)), entry))
        exe = folder / ('main.exe' if os.name == 'nt' else 'main')
        compile_c(c, exe)
        result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '42\n7\n')
