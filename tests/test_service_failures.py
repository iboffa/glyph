"""Adversarial service behavior, including deterministic syscall fault injection."""
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest

from glyph.backend import Emitter, compile_c
from glyph.checker import check
from glyph.syntax import parse
from test_glyph import BUILD, execute, native
from test_services import OPTIONAL, local_http


def harness(source, name, additions, transform=lambda text: text):
    BUILD.mkdir(parents=True, exist_ok=True)
    generated = Emitter().emit(check(parse(source)))
    generated = generated.replace('int main(int argc, char **argv)', 'int glyph_program_entry(int argc, char **argv)')
    path = BUILD / (name + '.c')
    path.write_text(transform(generated) + additions, encoding='utf-8')
    exe = path.with_suffix('.exe' if os.name == 'nt' else '')
    compile_c(path, exe)
    return exe



class FileFailureTests(unittest.TestCase):
    def test_read_write_and_close_failures_release_handles(self):
        def transform(text):
            start = text.index('#ifndef GLYPH_IO_RUNTIME_H')
            end = text.index('#endif', start) + len('#endif')
            section = text[start:end]
            for name in ('fread', 'fwrite', 'fclose', 'ferror'):
                section = section.replace(name+'(', 'g_test_'+name+'(')
            wrappers = r"""
static int test_fault;
static size_t g_test_fread(void *data,size_t size,size_t n,FILE *f) {
    return fread(data,size,test_fault==1 && n>1 ? 1 : n,f);
}
static int g_test_ferror(FILE *f) { return test_fault==1 || ferror(f); }
static size_t g_test_fwrite(const void *data,size_t size,size_t n,FILE *f) {
    return fwrite(data,size,test_fault==2 && n ? n-1 : n,f);
}
static int g_test_fclose(FILE *f) {
    int result=fclose(f);
    return test_fault==3 ? EOF : result;
}
"""
            return text[:start] + wrappers + section + text[end:]
        exe = harness('main>void\n  try_close(0)\n', 'fault_file_resources', r"""
int main(int argc,char **argv) {
    g_gc_init();
    if(argc!=2) return 1;
    g_str path={argv[1],(int64_t)strlen(argv[1])};
    int64_t data[]={0,255,42}; g_array bytes={data,3};
    test_fault=2;
    if(g_std_try_write_bytes(path,bytes,1,1).m_ok || g_files) return 2;
    test_fault=0;
    if(!g_std_try_write_bytes(path,bytes,1,1).m_ok) return 3;
    test_fault=1;
    g_record_BytesResult read=g_std_try_read_bytes(path,1,1);
    if(read.m_ok || read.m_value.len || g_files) return 4;
    test_fault=3;
    if(g_std_try_write_bytes(path,bytes,1,1).m_ok || g_files) return 5;
    test_fault=0;
    g_record_IntResult opened=g_std_try_open(path,(g_str){"r",1},1,1);
    if(!opened.m_ok) return 6;
    test_fault=3;
    if(g_std_try_close(opened.m_value,1,1).m_ok || g_files) return 7;
    test_fault=0;
    if(g_std_try_close(opened.m_value,1,1).m_ok) return 8;
    read=g_std_try_read_bytes(path,1,1);
    if(!read.m_ok || read.m_value.len!=3 || g_files) return 9;
    puts("resources released"); return 0;
}
""", transform)
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            result = execute(exe, Path(folder)/'data.bin')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'resources released\n')


class TCPFailureTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX EINTR/poll fault injection')
    def test_interrupted_wait_preserves_deadline(self):
        def transform(text):
            text = text.replace('poll(', 'g_test_poll(').replace('g_clock()', 'g_test_clock()')
            wrappers = '''
static int test_calls;
static double test_now;
static double g_test_clock(void) { return test_now; }
static int g_test_poll(struct pollfd *fds, nfds_t count, int timeout) {
    (void)fds; (void)count;
    test_calls++;
    if(test_calls==1) { test_now=0.040; errno=EINTR; return -1; }
    /* An interrupt consumed 40 ms of the original 100 ms budget. */
    if(timeout>61 || timeout<59) return 1;
    return 0;
}
'''
            return text.replace('static int g_tcp_wait', wrappers + 'static int g_tcp_wait', 1)
        exe = harness('main>void\n  try_tcp_close(0)\n', 'fault_tcp_deadline', '''
int main(void) {
    g_gc_init();
    if(g_tcp_wait(0,false,100)!=0 || test_calls!=2) return 1;
    puts("deadline preserved"); return 0;
}
''', transform)
        result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'deadline preserved\n')

    @unittest.skipIf(os.name == 'nt', 'POSIX interrupted send/recv injection')
    def test_interrupted_and_short_transfers_recover(self):
        def transform(text):
            text = text.replace('send(e->socket,', 'g_test_send(e->socket,')
            text = text.replace('recv(e->socket,', 'g_test_recv(e->socket,')
            wrappers = '''
static int test_sends, test_recvs;
static ssize_t g_test_send(g_socket s, const void *data, size_t count, int flags) {
    if(++test_sends==1) { errno=EINTR; return -1; }
    return send(s,data,count>3 ? 3 : count,flags);
}
static ssize_t g_test_recv(g_socket s, void *data, size_t count, int flags) {
    if(++test_recvs==1) { errno=EINTR; return -1; }
    return recv(s,data,count>2 ? 2 : count,flags);
}
'''
            return text.replace('static g_record_BytesResult g_std_try_tcp_read', wrappers+'static g_record_BytesResult g_std_try_tcp_read', 1)
        source = '''main>void
  listener := try_tcp_listen("127.0.0.1", 0, 8).value
  client := try_tcp_connect("127.0.0.1", try_tcp_port(listener).value, 1000).value
  peer := try_tcp_accept(listener, 1000).value
  wrote := try_tcp_write(client, [0, 255, 1, 2, 3, 4, 5])
  print(wrote.ok)
  if not wrote.ok
    exit(2)
  bytes:[int] = []
  while len(bytes) < 7
    part := try_tcp_read(peer, 7 - len(bytes))
    if not part.ok or len(part.value) == 0
      exit(3)
    for b:part.value
      bytes = push(bytes, b)
  print(try_base64_encode(bytes).value)
  print(try_tcp_close(peer).ok and try_tcp_close(client).ok and try_tcp_close(listener).ok)
'''
        exe = harness(source, 'fault_tcp_interrupt', '''
int main(int argc, char **argv) { return glyph_program_entry(argc,argv); }
''', transform)
        result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'true\nAP8BAgMEBQ==\ntrue\n')

    def test_peer_reset_is_recoverable(self):
        source = '''main>void
  client := try_tcp_connect("127.0.0.1", argi(0), 1000)
  if not client.ok
    exit(2)
  failed := false
  for i:range(100)
    if not failed
      wrote := try_tcp_write(client.value, fill(8192, 42))
      if not wrote.ok
        print(wrote.code)
        failed = true
  print(failed)
  print(try_tcp_close(client.value).ok)
'''
        exe = native(source, 'fault_tcp_reset')
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); listener.listen(1)
            def reset():
                import struct
                connection, _ = listener.accept()
                with connection:
                    # Abortive close forces RST, rather than an orderly EOF.
                    linger = struct.pack('hh' if os.name == 'nt' else 'ii', 1, 0)
                    connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
            thread = threading.Thread(target=reset, daemon=True); thread.start()
            try:
                result = execute(exe, listener.getsockname()[1])
            finally:
                thread.join(timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'R013\ntrue\ntrue\n')

    def test_many_socket_failures_release_descriptors(self):
        source = 'main>void\n  try_tcp_close(0)\n'
        exe = harness(source, 'fault_tcp_resources', '''
#ifndef _WIN32
#include <sys/resource.h>
#endif
int main(void) {
    g_gc_init();
#ifndef _WIN32
    /* Leaking even one descriptor per failed attempt exhausts this limit. */
    struct rlimit limit;
    if(getrlimit(RLIMIT_NOFILE,&limit)) return 7;
    if(limit.rlim_cur>128) limit.rlim_cur=128;
    if(setrlimit(RLIMIT_NOFILE,&limit)) return 8;
#endif
    g_record_IntResult listener=g_std_try_tcp_listen((g_str){"127.0.0.1",sizeof("127.0.0.1")-1},0,8,1,1);
    if(!listener.m_ok) return 1;
    int64_t port=g_std_try_tcp_port(listener.m_value,1,1).m_value;
    for(int i=0;i<160;i++) {
        if(g_std_try_tcp_listen((g_str){"127.0.0.1",sizeof("127.0.0.1")-1},port,8,1,1).m_ok) return 2;
    }
    if(!g_std_try_tcp_close(listener.m_value,1,1).m_ok) return 3;
    for(int i=0;i<160;i++) {
        if(g_std_try_tcp_connect((g_str){"127.0.0.1",sizeof("127.0.0.1")-1},port,50,1,1).m_ok) return 4;
    }
    if(g_tcp_handles) return 5;
    g_record_IntResult again=g_std_try_tcp_listen((g_str){"127.0.0.1",sizeof("127.0.0.1")-1},port,8,1,1);
    if(!again.m_ok || !g_std_try_tcp_close(again.m_value,1,1).m_ok) return 6;
    puts("resources released"); return 0;
}
''')
        result = execute(exe)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'resources released\n')


@unittest.skipUnless(OPTIONAL, 'optional system libraries are not enabled')
class DatabaseFailureTests(unittest.TestCase):
    def test_lock_contention_recovers_and_close_rolls_back(self):
        exe = native('''main>void
  first := try_db_open(arg(0)).value
  second := try_db_open(arg(0)).value
  try_db_exec(first, "CREATE TABLE x(value INTEGER)")
  try_db_exec(second, "PRAGMA busy_timeout=25")
  print(try_db_exec(first, "BEGIN IMMEDIATE; INSERT INTO x VALUES(1)").ok)
  failed := try_db_exec(second, "INSERT INTO x VALUES(2)")
  print(failed.code)
  print(try_db_close(first).ok)
  print(try_db_exec(second, "INSERT INTO x VALUES(3)").ok)
  statement := try_db_prepare(second, "SELECT value FROM x").value
  print(try_db_step(statement).value)
  print(try_db_column_int(statement, 0).value)
  print(try_db_close(second).code)
  print(try_db_step(statement).value)
  print(try_db_finalize(statement).ok)
  print(try_db_close(second).ok)
''', 'fault_db_lock')
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            result = execute(exe, Path(folder)/'locked.sqlite')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'true\nR015\ntrue\ntrue\ntrue\n3\nR015\nfalse\ntrue\ntrue\n')

    def test_failed_prepares_finalizes_and_opens_release_resources(self):
        exe = harness('main>void\n  try_db_open(":memory:")\n', 'fault_db_resources', '''
int main(int argc, char **argv) {
    g_gc_init();
    if(argc!=2) return 1;
    g_str invalid={argv[1],(int64_t)strlen(argv[1])};
    for(int i=0;i<300;i++) {
        if(g_std_try_db_open(invalid,1,1).m_ok) return 2;
        g_record_IntResult db=g_std_try_db_open((g_str){":memory:",sizeof(":memory:")-1},1,1);
        if(!db.m_ok) return 3;
        if(g_std_try_db_prepare(db.m_value,(g_str){"SELECT 1; SELECT 2",sizeof("SELECT 1; SELECT 2")-1},1,1).m_ok) return 4;
        if(g_statements) return 5;
        if(!g_std_try_db_exec(db.m_value,(g_str){"CREATE TABLE x(a UNIQUE); INSERT INTO x VALUES(1)",sizeof("CREATE TABLE x(a UNIQUE); INSERT INTO x VALUES(1)")-1},1,1).m_ok) return 6;
        g_record_IntResult stmt=g_std_try_db_prepare(db.m_value,(g_str){"INSERT INTO x VALUES(1)",sizeof("INSERT INTO x VALUES(1)")-1},1,1);
        if(!stmt.m_ok) return 7;
        if(g_std_try_db_step(stmt.m_value,1,1).m_ok) return 8;
        if(g_std_try_db_finalize(stmt.m_value,1,1).m_ok || g_statements) return 9;
        if(!g_std_try_db_close(db.m_value,1,1).m_ok || g_databases) return 10;
    }
    puts("resources released"); return 0;
}
''')
        with tempfile.TemporaryDirectory(dir=BUILD) as folder:
            result = execute(exe, Path(folder)/'missing'/'db.sqlite')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'resources released\n')


@unittest.skipUnless(OPTIONAL, 'optional system libraries are not enabled')
class HTTPFailureTests(unittest.TestCase):
    def test_truncated_body_headers_and_limit_failures_recover(self):
        exe = native('''main>void
  base := arg(0)
  for path:["/truncated", "/headers", "/large"]
    failed := try_http_request("GET", concat(base,path), [], [], 1000, 64, "")
    print(failed.code)
    print(not failed.ok and len(failed.value) == 0 and len(failed.headers) == 0 and failed.status == 0)
  print(try_http_request("GET", concat(base,"/get"), [], [], 1000, 64, "").ok)
''', 'fault_http_response')
        with local_http() as port:
            result = execute(exe, f'http://127.0.0.1:{port}')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'R014\ntrue\n'*3 + 'true\n')
