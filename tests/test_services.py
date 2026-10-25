import base64
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import random
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from glyph.backend import Emitter
from glyph.checker import check
from glyph.syntax import Diagnostic, parse
from test_glyph import BUILD, native, execute

OPTIONAL = os.name != 'nt' or os.environ.get('GLYPH_TEST_NATIVE_LIBS') == '1'


class SerializationTests(unittest.TestCase):
    def test_base64_vectors_and_rejections(self):
        rng = random.Random(4648)
        payloads = [b'', b'f', b'fo', b'foo', bytes(range(256))]
        payloads += [rng.randbytes(n) for n in range(1, 40)]
        lines = ['main>void']
        for payload in payloads:
            encoded = base64.b64encode(payload).decode()
            values = '[' + ','.join(map(str, payload)) + ']'
            lines += [f'  print(try_base64_encode({values}).value == "{encoded}")',
                      f'  print(try_base64_encode(try_base64_decode("{encoded}").value).value == "{encoded}")']
        bad = ['Zg', 'Zg=', 'Zg===', 'Zg==\n', 'Zh==', 'Zm9=', '=m9v', 'Zg==AAAA', '____', 'Zg\x00=']
        lines += ['  for text:[' + ','.join(json.dumps(x) for x in bad) + ']',
                  '    print(try_base64_decode(text).code)', '  print(try_base64_encode([256]).code)']
        proc = execute(native('\n'.join(lines)+'\n', 'services_base64'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'true\n' * (2*len(payloads)) + 'R016\n'*len(bad) + 'R009\n')

    def test_csv_multiline_unicode_and_errors(self):
        rows = [['a,b', 'quote"', 'line\r\nbreak', 'é🙂', '', '\x00'], ['1', '2', '3'], ['']]
        expressions = ['csv_row([' + ','.join(json.dumps(x) for x in row) + '])' for row in rows]
        source = '''main>void
  encoded := try_csv_write([''' + ','.join(expressions) + '''])
  print(json_quote(encoded.value))
  parsed := try_csv_parse(encoded.value)
  print(parsed.ok)
  print(len(parsed.value))
  for row:parsed.value
    decoded := try_csv_row(row)
    print(decoded.ok)
    print(try_json_array([json_quote(csv_row(decoded.value))]).value)
  print(len(try_csv_parse("").value))
  print(len(try_csv_row("").value))
  print(len(try_csv_row("a,").value))
  for bad:["\\\"unclosed", "a\\\"b", "\\\"a\\\"tail", "a\\rb", "a\\r"]
    print(try_csv_parse(bad).code)
  print(try_csv_row("a\\nb").code)
  print(try_csv_write(["a\\nb"]).code)
'''
        proc = execute(native(source, 'services_csv'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = proc.stdout.splitlines()
        serialized = json.loads(lines[0])
        self.assertEqual(list(csv.reader(io.StringIO(serialized, newline=''))), rows)
        self.assertEqual(lines[1:3], ['true', '3'])
        for i, row in enumerate(rows):
            self.assertEqual(lines[3+i*2], 'true')
            text = json.loads(lines[4+i*2])[0]
            self.assertEqual(next(csv.reader(io.StringIO(text, newline=''))), row)
        self.assertEqual(lines[9:], ['0', '1', '2'] + ['R016']*7)


class TCPTests(unittest.TestCase):
    def test_loopback_client_server_timeouts_and_close(self):
        proc = execute(native('''main>void
  server := try_tcp_listen("127.0.0.1", 0, 8)
  if not server.ok
    eprint(server.message)
    exit(1)
  port := try_tcp_port(server.value)
  print(port.ok and port.value > 0)
  print(try_tcp_accept(server.value, 10).code)
  client := try_tcp_connect("127.0.0.1", port.value, 100)
  print(client.ok)
  peer := try_tcp_accept(server.value, 100)
  print(peer.ok)
  print(try_tcp_read(peer.value, 1).code)
  print(try_tcp_write(client.value, [0,255,128,42]).value)
  received:[int] = []
  while len(received) < 4
    chunk := try_tcp_read(peer.value, 4 - len(received))
    if not chunk.ok or len(chunk.value) == 0
      exit(2)
    for byte:chunk.value
      received = push(received, byte)
  print(try_base64_encode(received).value)
  print(try_tcp_write(peer.value, [99]).value)
  print(try_tcp_read(client.value, 1).value[0])
  print(try_tcp_write(client.value, [256]).code)
  print(try_tcp_read(server.value, 1).code)
  print(try_tcp_close(client.value).ok)
  eof := try_tcp_read(peer.value, 1)
  print(eof.ok and len(eof.value) == 0)
  print(try_tcp_close(client.value).code)
  print(try_tcp_close(peer.value).ok)
  print(try_tcp_close(server.value).ok)
  print(try_tcp_port(server.value).code)
  print(try_tcp_connect("", 1, 1).code)
  print(try_tcp_listen("127.0.0.1", 65536, 1).code)
''', 'services_tcp'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'true\nR013\ntrue\ntrue\nR013\n4\nAP+AKg==\n1\n99\nR009\nR013\ntrue\ntrue\nR013\ntrue\ntrue\nR013\nR013\nR013\n')


@unittest.skipUnless(OPTIONAL, 'install system libcurl/SQLite and set GLYPH_TEST_NATIVE_LIBS=1 on Windows')
class DatabaseTests(unittest.TestCase):
    def test_prepared_values_transactions_and_lifetimes(self):
        source = r'''main>void
  db := try_db_open(arg(0))
  print(db.ok)
  print(try_db_exec(db.value, "CREATE TABLE items(i INTEGER, f REAL, t TEXT, b BLOB, n)").ok)
  insert := try_db_prepare(db.value, "INSERT INTO items VALUES(?,?,?,?,?)")
  print(insert.ok)
  print(try_db_bind_int(insert.value, 1, 9223372036854775807).ok)
  print(try_db_bind_float(insert.value, 2, 1.25).ok)
  print(try_db_bind_text(insert.value, 3, "O'Reilly; DROP TABLE items;--\u0000é").ok)
  print(try_db_bind_bytes(insert.value, 4, [0,255]).ok)
  print(try_db_bind_null(insert.value, 5).ok)
  step := try_db_step(insert.value)
  print(step.ok and not step.value)
  print(try_db_step(insert.value).code)
  print(try_db_bind_int(insert.value, 1, 0).code)
  print(try_db_changes(db.value).value)
  print(try_db_last_id(db.value).value)
  print(try_db_close(db.value).code)
  print(try_db_reset(insert.value).ok)
  print(try_db_bind_int(insert.value, 0, 0).code)
  print(try_db_exec(db.value, "BEGIN").ok)
  print(try_db_step(insert.value).ok)
  print(try_db_exec(db.value, "ROLLBACK").ok)
  print(try_db_finalize(insert.value).ok)
  print(try_db_finalize(insert.value).code)
  query := try_db_prepare(db.value, "SELECT * FROM items")
  print(try_db_columns(query.value).value)
  print(try_db_column_name(query.value, 0).value)
  print(try_db_column_int(query.value, 0).code)
  print(try_db_step(query.value).value)
  print(try_db_column_int(query.value, 0).value)
  print(try_db_column_float(query.value, 1).value)
  text := try_db_column_text(query.value, 2)
  print(text.value == "O'Reilly; DROP TABLE items;--\u0000é")
  blob := try_db_column_bytes(query.value, 3)
  print(try_base64_encode(blob.value).value)
  print(try_db_column_type(query.value, 4).value)
  print(try_db_column_int(query.value, 4).code)
  print(try_db_column_text(query.value, 5).code)
  print(try_db_step(query.value).value)
  print(try_db_finalize(query.value).ok)
  print(text.value == "O'Reilly; DROP TABLE items;--\u0000é")
  print(try_db_prepare(db.value, "SELECT 1; SELECT 2").code)
  print(try_db_prepare(db.value, "").code)
  print(try_db_exec(db.value, "INVALID SQL").code)
  print(try_db_exec(db.value, "SELECT 1\u0000;DROP TABLE items").code)
  print(try_db_close(db.value).ok)
  print(try_db_exec(db.value, "SELECT 1").code)
  reopened := try_db_open(arg(0))
  print(reopened.ok and reopened.value != db.value)
  print(try_db_close(reopened.value).ok)
'''
        exe = native(source, 'services_db')
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            with patch.dict(os.environ, GLYPH_GC_STRESS='1'):
                proc = execute(exe, Path(directory) / 'store.sqlite')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        expected = ['true']*9 + ['R015','R015','1','1','R015','true','R015','true','true','true','true','R015',
            '5','i','R015','true','9223372036854775807','1.25','true','AP8=','null','R015','R015','false','true','true',
            'R015','R015','R015','R015','true','R015','true','true']
        self.assertEqual(proc.stdout.splitlines(), expected)

    def test_empty_values_invalid_utf8_and_failed_statement_reset(self):
        proc = execute(native(r'''main>void
  db := try_db_open(":memory:").value
  try_db_exec(db, "CREATE TABLE x(a UNIQUE)")
  ins := try_db_prepare(db, "INSERT INTO x VALUES(?)").value
  try_db_bind_int(ins, 1, 1)
  print(try_db_step(ins).ok)
  try_db_reset(ins)
  print(try_db_step(ins).code)
  print(try_db_reset(ins).code)
  print(try_db_bind_int(ins, 1, 2).ok)
  print(try_db_step(ins).ok)
  try_db_finalize(ins)
  q := try_db_prepare(db, "SELECT ?, ?, CAST(x'ff' AS TEXT)").value
  print(try_db_bind_text(q, 1, "").ok)
  print(try_db_bind_bytes(q, 2, []).ok)
  print(try_db_step(q).value)
  print(try_db_column_type(q, 0).value)
  print(try_db_column_type(q, 1).value)
  print(try_db_column_text(q, 0).value == "")
  print(len(try_db_column_bytes(q, 1).value))
  print(try_db_column_text(q, 2).code)
  print(try_db_finalize(q).ok)
  print(try_db_close(db).ok)
''', 'services_db_errors'))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ['true','R015','R015','true','true','true','true','true','text','bytes','true','0','R015','true','true'])


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        status, payload = 200, b'\x00\xffok'
        if self.path == '/missing':
            status, payload = 404, b'missing'
        if self.path == '/large':
            payload = b'x' * 10000
        if self.path == '/slow':
            time.sleep(0.2)
        if self.path == '/redirect':
            status, payload = 302, b''
        try:
            self.send_response(status)
            if status == 302:
                self.send_header('Location', '/get')
            if self.path == '/headers':
                self.send_header('X-Large', 'x' * 70000)
            self.send_header('Content-Length', str(len(payload) + (100 if self.path == '/truncated' else 0)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            pass

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        self.send_response(201)
        self.send_header('X-Echo', self.headers.get('X-Token', ''))
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def local_http(tls=None):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    if tls:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*'}):
            yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@unittest.skipUnless(OPTIONAL, 'install system libcurl/SQLite and set GLYPH_TEST_NATIVE_LIBS=1 on Windows')
class HTTPTests(unittest.TestCase):
    def test_http_binary_status_headers_limits_and_timeouts(self):
        exe = native(r'''main>void
  base := arg(0)
  r := try_http_request("GET", concat(base, "/get"), [], [], 1000, 10000, "")
  print(r.ok)
  print(r.status)
  print(try_base64_encode(r.value).value)
  print(len(r.headers) > 0)
  r = try_http_request("POST", base, ["X-Token: hello"], [0,255,42], 1000, 1000, "")
  print(r.ok)
  print(r.status)
  print(try_base64_encode(r.value).value)
  print(try_http_request("GET", concat(base, "/missing"), [], [], 1000, 1000, "").status)
  print(try_http_request("GET", concat(base, "/redirect"), [], [], 1000, 1000, "").status)
  print(try_http_request("HEAD", base, [], [], 1000, 0, "").ok)
  print(try_http_request("GET", concat(base, "/large"), [], [], 1000, 10, "").code)
  print(try_http_request("GET", concat(base, "/slow"), [], [], 30, 1000, "").code)
  print(try_http_request("GET", "file:///tmp/forbidden", [], [], 1000, 1000, "").code)
  print(try_http_request("GET", base, ["X: bad\r\nInjected: yes"], [], 1000, 1000, "").code)
  print(try_http_request("GET", base, ["X: bad\u0001"], [], 1000, 1000, "").code)
  print(try_http_request("POST", base, ["Content-Length: 999"], [], 1000, 1000, "").code)
  print(try_http_request("GET", base, [], [256], 1000, 1000, "").code)
''', 'services_http')
        with local_http() as port:
            with patch.dict(os.environ, GLYPH_GC_STRESS='1'):
                proc = execute(exe, f'http://127.0.0.1:{port}')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.splitlines(), ['true','200','AP9vaw==','true','true','201','AP8q','404','302','true']+['R014']*7)

    @unittest.skipUnless(shutil.which('openssl'), 'openssl is required to generate a temporary TLS test certificate')
    def test_tls_trust_and_hostname_verification(self):
        exe = native('''main>void
  print(try_http_request("GET", arg(0), [], [], 2000, 1000, arg(2)).ok)
  print(try_http_request("GET", arg(0), [], [], 2000, 1000, "").code)
  print(try_http_request("GET", arg(1), [], [], 2000, 1000, arg(2)).code)
''', 'services_tls')
        with tempfile.TemporaryDirectory(dir=BUILD) as directory:
            cert, key = Path(directory)/'cert.pem', Path(directory)/'key.pem'
            subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                            '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost',
                            '-keyout', str(key), '-out', str(cert)], check=True, capture_output=True)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(cert, key)
            with local_http(context) as port:
                proc = execute(exe, f'https://localhost:{port}', f'https://127.0.0.1:{port}', cert)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, 'true\nR014\nR014\n')


class ServiceFrontendTests(unittest.TestCase):
    def test_types_and_optional_link_markers(self):
        cases = [('try_tcp_connect("host", "80", 1)', 'G102'), ('try_http_request("GET")', 'G107'),
                 ('try_db_bind_bytes(1, 1, ["x"])', 'G102'), ('try_csv_row(["x"])', 'G102')]
        for expr, code in cases:
            with self.subTest(expr=expr), self.assertRaises(Diagnostic) as caught:
                check(parse('main>void\n  '+expr+'\n'))
            self.assertEqual(caught.exception.code, code)
        ordinary = Emitter().emit(check(parse('main>void\n  print(1)\n')))
        self.assertNotIn('#include <curl/curl.h>', ordinary)
        self.assertNotIn('#include <sqlite3.h>', ordinary)
        self.assertNotIn('#include <sys/socket.h>', ordinary)
        user_prefix = Emitter().emit(check(parse('try_db_user>int = 1\nmain>void\n  print(try_db_user())\n')))
        self.assertNotIn('#include <sqlite3.h>', user_prefix)
        for prefix, call, include in [('HTTP', 'try_http_request("GET","file:x",[],[],1,1,"")', '<curl/curl.h>'),
                                      ('DB', 'try_db_open(":memory:")', '<sqlite3.h>'),
                                      ('TCP', 'try_tcp_close(0)', '<sys/socket.h>')]:
            emitted = Emitter().emit(check(parse('main>void\n  '+call+'\n')))
            self.assertIn('#define GLYPH_'+prefix+' 1', emitted)
            self.assertIn('#include '+include, emitted)
