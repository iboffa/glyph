"""Concurrency acceptance, rejection, native overlap, GC and shutdown evidence."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from glyph.syntax import parse, Diagnostic
from glyph.checker import check
from glyph.formatter import format_source
from glyph.backend import Emitter, compile_c
from test_glyph import native, BUILD, ROOT


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        if sys.platform not in {"darwin", "linux"} or os.environ.get("GLYPH_SKIP_EXECUTION") == "1":
            self.skipTest("native concurrency execution requires macOS/Linux and execution permission")
    def run_source(self, source, name, expected, optimizations=('2',), stress=False):
        formatted = format_source(source)
        self.assertEqual(format_source(formatted), formatted)
        for opt in optimizations:
            BUILD.mkdir(parents=True, exist_ok=True)
            exe = BUILD / ('concurrency_' + name + opt)
            c = exe.with_suffix('.c')
            c.write_text(Emitter().emit(check(parse(formatted))))
            compile_c(c, exe, opt)
            for workers in ('1', '2', '4'):
                env = dict(os.environ, GLYPH_WORKERS=workers, GLYPH_GC_STRESS='1' if stress else '0')
                proc = subprocess.run([str(exe)], capture_output=True, text=True, env=env, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stdout, expected)

    def reject(self, source, code='G116'):
        with self.assertRaises(Diagnostic) as caught:
            check(parse(source))
        self.assertEqual(caught.exception.code, code)

    def test_map_sizes_nested_captures_generics(self):
        self.run_source('''square[T] x:T>T = x * x
nested x:int>int = sum(par_map([x, x + 1], square[int]))
main>void
  empty:[int] = []
  print(len(par_map(empty, square[int])))
  offset := 5
  print(par_map([1, 2], fn(x:int)>int = x + offset)[1])
  a := par_map(range(4103), square[int])
  print(a[4102])
  print(sum(a))
  print(par_map([2, 3], nested)[1])
  print(par_map([1.5, 2.0], fn(x:f64)>f64 = x * 2.0)[0])
''', 'map', '0\n7\n16826404\n23015716955\n25\n3\n', ('0', '2', '3'), True)

    def test_map_unsafe_effects_and_transitive_aliases(self):
        for typ, value, body in (
            ('[int]', '[1]', 'a[0] + x'),
            ('list[int]', 'list([1])', 'a.get(0) + x'),
            ('Box', 'Box([1])', 'a.items[0] + x'),
            ('fn(int)>int', 'fn(y:int)>int = y', 'a(x)'),
        ):
            self.reject(f'type Box\n  items:[int]\nmain>void\n  a:{typ} = {value}\n  out := par_map([1], fn(x:int)>int = {body})\n')
        for helper in ('exit(x)', 'print(x)', 'try_close(x)', 'gui_close()'):
            # Some APIs differ in result type, so use an expression statement.
            self.reject(f'bad x:int>int\n  {helper}\n  ret x\nmain>void\n  a := par_map([1], bad)\n')
        self.reject('bad x:int>int\n  unsafe\n    ret x\nmain>void\n  a := par_map([1], bad)\n')
        self.reject('apply f:fn(int)>int, x:int>int = f(x)\nbad x:int>int = apply(fn(y:int)>int = y, x)\nmain>void\n  a := par_map([1], bad)\n')

    def test_worker_checked_traps(self):
        for name, callback, code in (
            ('overflow', 'x * 9223372036854775807', 'R001'),
            ('bounds', '[1][x]', 'R003'),
        ):
            exe = native(f'main>void\n  a := par_map(range(4097), fn(x:int)>int = {callback})\n', 'concurrency_' + name)
            proc = subprocess.run([str(exe)], capture_output=True, text=True, env=dict(os.environ, GLYPH_WORKERS='2'), timeout=20)
            self.assertEqual(proc.returncode, 70)
            self.assertIn(code, proc.stderr)

    def test_instrumented_simultaneous_execution(self):
        # A condition-variable rendezvous requires two live callbacks; serial
        # execution cannot pass. No timing sleeps or speedup inference.
        source = '#define GLYPH_CONCURRENCY 1\n#define G_FILE_JSON "\\\"overlap\\\""\n'
        source += (ROOT / 'glyph/runtime.h').read_text()
        source += (ROOT / 'glyph/std_runtime.h').read_text()
        source += (ROOT / 'glyph/concurrency_runtime.h').read_text()
        source += r'''
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t both=PTHREAD_COND_INITIALIZER;
static int arrived;
static void work(void *env, g_array in, g_array out, int64_t start, int64_t end) {
    pthread_mutex_lock(&lock);
    if (arrived<2) {
        ++arrived; pthread_cond_broadcast(&both);
        while (arrived<2) pthread_cond_wait(&both,&lock);
    }
    pthread_mutex_unlock(&lock);
    for (int64_t j=start;j<end;j++) ((int64_t*)out.data)[j]=j+1;
}
int main(void) {
    g_gc_init();
    for (int repeat=0;repeat<3;repeat++) {
        arrived=0;
        g_array a=g_range(4097,1,1);
        g_array b=g_par_map(a,sizeof(int64_t),work,NULL,1,1);
        if (arrived!=2 || ((int64_t*)b.data)[4096]!=4097) return 1;
        g_concurrency_shutdown();
    }
    return 0;
}
'''
        path = BUILD / 'concurrency_overlap.c'
        path.write_text(source)
        exe = BUILD / 'concurrency_overlap'
        compile_c(path, exe)
        proc = subprocess.run([str(exe)], capture_output=True, text=True, env=dict(os.environ, GLYPH_WORKERS='2', GLYPH_GC_STRESS='1'), timeout=20)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_tasks_results_nested_scopes_and_early_return(self):
        self.run_source('''type Value
  text:str
  number:int
make[T] value:T>T = value
work>Value = Value(concat("hello", " task"), 42)
nested>IntResult
  scope
    t := spawn(work)
    scope
      n := spawn(fn()>int = 5)
      ret IntResult(false, wait(t).number + wait(n), "test", "recoverable")
main>void
  result := nested()
  print(result.ok)
  print(result.value)
  i := 0
  while i < 30
    scope
      offset := i
      a := spawn(fn()>int = make[int](offset))
      if wait(a) != i
        exit(1)
      if wait(a) != i
        exit(2)
    i += 1
  scope
    t := spawn(work)
    print(task_status(t).ok)
    print(wait(t).text)
''', 'tasks', 'false\n47\ntrue\nhello task\n', ('0', '2', '3'), True)

    def test_task_handle_escape_and_unsafe_results(self):
        for statement in ('copy := t', 'ret t', 't = spawn(work)', 'f := fn()>int = wait(t)'):
            self.reject('work>int = 1\nbad>void\n  scope\n    t := spawn(work)\n    ' + statement + '\nmain>void\n  bad()\n', 'G102' if statement == 'ret t' else 'G117')
        self.reject('work>int = 1\nmain>void\n  t := spawn(work)\n', 'G117')
        self.reject('work>[int] = [1]\nmain>void\n  scope\n    t := spawn(work)\n')
        self.reject('type Box\n  items:list[int]\nwork>Box = Box(list([1]))\nmain>void\n  scope\n    t := spawn(work)\n')
        self.reject('take t:task[int]>int = wait(t)\nmain>void\n  print(1)\n', 'G117')

    def test_task_resource_exhaustion_and_reuse(self):
        source = '''work>int = 42
main>void
  scope
    first := spawn(work)
    second := spawn(work)
    print(task_status(first).ok)
    print(task_status(second).ok)
    print(task_status(second).code)
    print(wait(first))
    third := spawn(work)
    print(task_status(third).ok)
    print(wait(third))
'''
        exe = native(source, 'concurrency_task_limit')
        proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20, env=dict(os.environ, GLYPH_TASK_LIMIT='1'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'true\nfalse\nR018\n42\ntrue\n42\n')

    def test_channels_fifo_payloads_gc_and_scope_join(self):
        self.run_source('''union Message
  Text value:str
  End
produce c:channel[Message]>int
  i := 0
  while i < 20
    send(c, Message.Text(concat("item", str_i64(i))))
    i += 1
  send(c, Message.End())
  close(c)
  ret 20
show m:Message>void
  match m
    case Text(value)
      print(value)
    case End()
      print("end")
main>void
  c:channel[Message] = channel(2)
  scope
    t := spawn(fn()>int = produce(c))
    if not task_status(t).ok
      close(c)
    while receive(c, show)
      marker := concat("force", " collection")
    print(wait(t))
  close(c)
  print(send(c, Message.End()))
  print(receive(c, show))
''', 'channels', ''.join(f'item{i}\n' for i in range(20)) + 'end\n20\nfalse\nfalse\n', ('0', '2', '3'), True)

    def test_channel_close_drains_and_empty_payload_not_eof(self):
        self.run_source('''show s:str>void
  print(len(s))
main>void
  c:channel[str] = channel(2)
  print(send(c, ""))
  print(send(c, concat("a", "b")))
  close(c)
  close(c)
  print(receive(c, show))
  print(receive(c, show))
  print(receive(c, show))
  print(send(c, "later"))
''', 'drain', 'true\ntrue\n0\ntrue\n2\ntrue\nfalse\nfalse\n', stress=True)

    def test_channel_tasks_progress_with_one_cpu_worker(self):
        # Two capacity-one channels make a bounded handshake, including closure
        # wakeup. CPU worker count cannot starve blocking task threads.
        self.run_source('''ignore value:int>void
  ret
consumer data:channel[int], ack:channel[int]>int
  count := 0
  while receive(data, ignore)
    send(ack, count)
    count += 1
  close(ack)
  ret count
producer data:channel[int], ack:channel[int]>int
  i := 0
  while i < 50
    send(data, i)
    receive(ack, ignore)
    i += 1
  close(data)
  ret i
main>void
  data:channel[int] = channel(1)
  ack:channel[int] = channel(1)
  scope
    a := spawn(fn()>int = consumer(data, ack))
    b := spawn(fn()>int = producer(data, ack))
    if not task_status(a).ok or not task_status(b).ok
      close(data)
      close(ack)
    print(wait(a))
    print(wait(b))
''', 'handshake', '50\n50\n', stress=True)

    def test_channel_rejections_and_capacity(self):
        for typ in ('[int]', 'list[int]', 'Box', 'Nested', 'fn(int)>int', '*int', 'channel[int]'):
            self.reject('type Box\n  items:[int]\nunion Nested\n  Data value:Box\nmain>void\n  c:channel[' + typ + '] = channel(1)\n')
        self.reject('main>void\n  c:channel[int] = channel(1)\n  a := par_map([1], fn(x:int)>int = helper(c, x))\nhelper c:channel[int], x:int>int\n  send(c, x)\n  ret x\n')
        exe = native('main>void\n  c:channel[int] = channel(0)\n', 'concurrency_capacity')
        proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 70)
        self.assertIn('R018', proc.stderr)

    def test_instrumented_close_wakeups_roots_and_creation_failure(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        source = BUILD / 'concurrency_runtime_harness.c'
        # Keep marker in this translation unit for build feature detection.
        source.write_text('#define GLYPH_CONCURRENCY 1\n#define GLYPH_GC 1\n#include "' + str(ROOT / 'tests/concurrency_runtime_harness.c') + '"\n')
        exe = BUILD / 'concurrency_runtime_harness'
        compile_c(source, exe)
        proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, GLYPH_GC_STRESS='1'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        failed = subprocess.run([str(exe), 'pool-failure'], capture_output=True, text=True, timeout=20,
                                env=dict(os.environ, GLYPH_WORKERS='4'))
        self.assertEqual(failed.returncode, 70)
        self.assertIn('R018', failed.stderr)
        fatal = subprocess.run([str(exe), 'fatal'], capture_output=True, text=True, timeout=20)
        self.assertEqual(fatal.returncode, 70)
        self.assertIn('R001', fatal.stderr)

    def test_safe_aggregate_capabilities_and_multiple_producers(self):
        self.run_source('''type Message
  producer:int
  index:int
type Endpoint
  messages:channel[Message]
produce endpoint:Endpoint, id:int>int
  i := 0
  while i < 30
    send(endpoint.messages, Message(id, i))
    i += 1
  ret i
check_order state:[int], message:Message>void
  if state[message.producer] != message.index
    exit(3)
  state[message.producer] += 1
main>void
  c:channel[Message] = channel(2)
  endpoint := Endpoint(c)
  state := [0, 0]
  consume := fn(message:Message)>void = check_order(state, message)
  scope
    a := spawn(fn()>int = produce(endpoint, 0))
    b := spawn(fn()>int = produce(endpoint, 1))
    if not task_status(a).ok or not task_status(b).ok
      exit(1)
    i := 0
    while i < 60
      receive(c, consume)
      i += 1
    close(c)
    print(wait(a) + wait(b))
  print(state[0])
  print(state[1])
''', 'multi_producer', '60\n30\n30\n', stress=True)

    def test_imported_generic_functions_methods_and_rejections(self):
        import tempfile
        from glyph.modules import load_program
        with tempfile.TemporaryDirectory(dir=BUILD) as temporary:
            folder = Path(temporary)
            library = folder / 'library.gly'
            library.write_text('''type Point
  value:int
  doubled>int = self.value * 2
compute[T] value:T>T = value * value
safe x:int>int = Point(compute[int](x)).doubled()
unsafe_helper x:int>int
  print(x)
  ret x
''')
            main = folder / 'main.gly'
            main.write_text('import safe from "./library.gly"\nmain>void\n  print(sum(par_map([1, 2, 3], safe)))\n')
            c = folder / 'main.c'
            c.write_text(Emitter().emit(check(load_program(main)), str(main)))
            exe = folder / 'main'
            compile_c(c, exe)
            proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
            self.assertEqual((proc.returncode, proc.stdout), (0, '28\n'), proc.stderr)
            main.write_text('import unsafe_helper from "./library.gly"\nmain>void\n  a := par_map([1], unsafe_helper)\n')
            with self.assertRaises(Diagnostic) as caught:
                check(load_program(main))
            self.assertEqual(caught.exception.code, 'G116')

    def test_scope_exit_joins_unwaited_child_and_results_survive(self):
        self.run_source('''make>str = concat("survives", " scope")
result>str
  scope
    t := spawn(make)
    ret wait(t)
main>void
  value := result()
  for i:range(20)
    garbage := concat("allocation", str_i64(i))
  print(value)
''', 'result_root', 'survives scope\n', stress=True)
        # A child trap must occur even when its handle is never explicitly waited.
        exe = native('bad>int = [1][2]\nmain>void\n  scope\n    t := spawn(bad)\n    ret\n', 'concurrency_unwaited')
        proc = subprocess.run([str(exe)], capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, 70)
        self.assertIn('R003', proc.stderr)

    def test_main_thread_services_coexist_with_concurrency(self):
        self.run_source('''work>int = 42
main>void
  scope
    t := spawn(work)
    db := try_db_open(":memory:")
    print(db.ok)
    if db.ok
      print(try_db_close(db.value).ok)
    print(wait(t))
''', 'main_services', 'true\ntrue\n42\n')
        if sys.platform == 'darwin':
            self.run_source('work>int = 42\nmain>void\n  scope\n    t := spawn(work)\n    print(wait(t))\n  gui_close()\n', 'main_gui', '42\n')


class ConcurrencyPlatformTests(unittest.TestCase):
    def test_unsupported_build_has_explicit_diagnostic(self):
        BUILD.mkdir(parents=True, exist_ok=True)
        source = BUILD / 'concurrency_unsupported.c'
        source.write_text('#define GLYPH_CONCURRENCY 1\n')
        with patch('glyph.backend.sys.platform', 'win32'):
            with self.assertRaises(Diagnostic) as caught:
                compile_c(source, BUILD / 'unsupported')
        self.assertEqual(caught.exception.code, 'G203')
