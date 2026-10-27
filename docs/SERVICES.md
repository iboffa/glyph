# Networking, HTTP/TLS, SQLite, CSV and Base64

These builtins are available in both compilers. Calls named `try_` return
records with `ok`, `value`, `code`, and `message`, following the existing
[systems API](SYSTEMS.md). Always check `ok`. Successful socket handles,
database handles and statement handles are positive process-local integers.
Each API has a separate handle namespace: pass a handle only to its own API.
IDs are never reused within a namespace. Garbage collection does not close
sockets or databases or finalize statements; release each explicitly.

## Build dependencies

TCP, CSV, and Base64 use the existing C runtime/toolchain. HTTP uses system
libcurl; SQLite uses system SQLite. These headers and libraries are needed
only when the program calls their APIs. Both emitters add feature markers and
runtime adapters; both build drivers add `-lcurl` / `-lsqlite3` as needed.
The Python driver uses an installed `clang` or `cc` for HTTP/SQLite programs
so it can use that compiler's system library search paths. Other console
programs continue to use the bundled Zig toolchain. The native compiler uses
its existing `--cc` selection. A program combining GUI and these libraries
uses the existing macOS GUI compiler plus the additional libraries.

On macOS, Apple's Command Line Tools SDK supplies curl and SQLite headers and
libraries. On Debian/Ubuntu, install `build-essential`, `libcurl4-openssl-dev`,
and `libsqlite3-dev`. For nonstandard installations, configure the system
compiler's `CPATH` and `LIBRARY_PATH`. Windows HTTP/SQLite builds use MSYS2's
UCRT64 packages `mingw-w64-ucrt-x86_64-clang`, `mingw-w64-ucrt-x86_64-curl`,
`mingw-w64-ucrt-x86_64-sqlite3`, and `mingw-w64-ucrt-x86_64-openssl`.
Put the installation's `ucrt64/bin` first on PATH when using Windows Python;
it supplies the compiler, headers, import libraries and runtime DLLs.
The TCP adapter has Winsock support and links
`ws2_32` on Windows through the Python driver. Native compiler build
orchestration still requires a POSIX host.

The service tests run local loopback servers. Sandboxes that prohibit socket
binding cannot execute those tests. On Windows the optional HTTP/SQLite tests
are skipped unless `GLYPH_TEST_NATIVE_LIBS=1` is set after installing their
dependencies. TLS tests generate a temporary certificate with `openssl` and
never modify the system trust store.

CI exercises these dependencies on Windows and Linux and uses macOS 15 with
Xcode 16.4 for compatibility with the pinned Zig 0.14.1 compiler. See
[verification results](VERIFICATION.md) for tested revisions and limitations.

## TCP

| Call | Result | Contract |
| --- | --- | --- |
| `try_tcp_connect(host:str, port:int, timeout_ms:int)` | `IntResult` | Resolve and connect to a TCP peer. Ports are 1–65535. |
| `try_tcp_listen(host:str, port:int, backlog:int)` | `IntResult` | Bind/listen. Port zero chooses an ephemeral port; empty host binds a wildcard address. |
| `try_tcp_port(handle:int)` | `IntResult` | Return the socket's local port. |
| `try_tcp_accept(listener:int, timeout_ms:int)` | `IntResult` | Accept a connection, setting its read/write timeout. |
| `try_tcp_read(connection:int, count:int)` | `BytesResult` | Read up to a positive count. Empty success means peer EOF. |
| `try_tcp_write(connection:int, bytes:[int])` | `IntResult` | Validate bytes and send all; success reports the sent count. |
| `try_tcp_close(handle:int)` | `BoolResult` | Close a connection or listener and invalidate its ID. |

Byte arrays use elements 0–255. Invalid byte values use `R009`; socket errors,
timeouts and invalid socket arguments use `R013`. Counts, backlogs and
timeouts must be positive and at most `INT_MAX`. Invalid handles and attempts
to read/write a listener fail recoverably. Closing invalidates a handle even
if the operating system reports an error during close.

TCP is a byte stream with no message boundaries. Reads can be short; collect
bytes until your protocol's expected length or delimiter. Writes can partly
reach the peer before an error. Failed results do not expose partial progress.
Connect timeout applies to each resolved address attempt; read/write timeouts
cover each complete call, including retries after interruption and all partial
transfers. The implementation uses nonblocking sockets internally to preserve
that deadline while presenting a blocking API. Name resolution is synchronous
and is not bounded by the connect timeout. This is blocking, single-threaded
TCP, with no UDP, asynchronous event loop, TLS socket wrapper, or HTTP server
framework. Bind a loopback address explicitly for local-only listeners.

```gly
main>void
  socket := try_tcp_connect("127.0.0.1", 9000, 1000)
  if not socket.ok
    eprint(socket.message)
    exit(1)
  sent := try_tcp_write(socket.value, encode_utf8("hello\n"))
  closed := try_tcp_close(socket.value)
  if not sent.ok or not closed.ok
    eprint("connection write or close failed")
    exit(1)
```

## HTTP and HTTPS

```text
try_http_request(method:str, url:str, headers:[str], body:[int],
                 timeout_ms:int, max_response_bytes:int, ca_file:str) > HttpResult
```

`HttpResult` has fields in this constructor order:

| Field | Type | Meaning |
| --- | --- | --- |
| `ok` | `bool` | Transport completed successfully. |
| `value` | `[int]` | Binary response body. |
| `code` | `str` | Empty on success, `R014` on failure. |
| `message` | `str` | Empty on success, descriptive failure text otherwise. |
| `status` | `int` | HTTP status code; zero on failure. |
| `headers` | `[int]` | Raw received header bytes, including status lines and interim header blocks. |

Methods are `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, and `OPTIONS`.
URLs must start with lowercase `http://` or `https://`; other protocols are
rejected. Supply headers as `"Name: value"` strings. CR, LF, NUL and invalid
control characters are rejected. The runtime manages Content-Length and
Transfer-Encoding. A HEAD request must have an empty body.

HTTPS verifies both certificate trust and hostname. An empty `ca_file` uses
libcurl's configured default trust roots; a nonempty path supplies a CA bundle.
There is no option to disable verification. This follows libcurl's independent
[peer](https://curl.se/libcurl/c/CURLOPT_SSL_VERIFYPEER.html) and
[hostname](https://curl.se/libcurl/c/CURLOPT_SSL_VERIFYHOST.html) checks.
Proxy environment variables retain libcurl's behavior.

HTTP errors such as 404 and 500 are successful transport results: inspect
`status`. Redirects are returned rather than automatically followed. The
request has a positive timeout in milliseconds. The body limit is nonnegative
and enforced while receiving, with a separate 64 KiB aggregate header limit.
Exceeding either limit returns failure with empty payloads. libcurl's resolver
backend determines whether DNS resolution can honor the timeout. There is no
streaming response API, shared cookie jar, or automatic retry. A timeout can
occur after a remote server has processed a request.

```gly
main>void
  response := try_http_request("GET", arg(0), ["Accept: application/json"], [], 5000, 1048576, "")
  if not response.ok
    eprint(response.message)
    exit(1)
  print(response.status)
  text := try_decode_utf8(response.value)
  if text.ok
    print(text.value)
```

## SQLite

Use SQLite for an embedded database file or `":memory:"` for a private in-memory
database. This API does not provide PostgreSQL/MySQL drivers or an ORM.
Database and statement handles have separate namespaces and must not be mixed.

| Call | Result | Contract |
| --- | --- | --- |
| `try_db_open(path:str)` | `IntResult` | Open/create a database, with a five-second SQLite busy timeout. Empty/NUL paths are rejected. |
| `try_db_close(db:int)` | `BoolResult` | Close; if statements remain, fail and keep the database usable. |
| `try_db_exec(db:int, sql:str)` | `BoolResult` | Execute trusted SQL, including multiple statements and transaction commands. |
| `try_db_prepare(db:int, sql:str)` | `IntResult` | Prepare exactly one statement. Only whitespace may follow it. |
| `try_db_bind_int(stmt:int, index:int, value:int)` | `BoolResult` | Bind a signed 64-bit integer. |
| `try_db_bind_float(stmt:int, index:int, value:f64)` | `BoolResult` | Bind a finite floating-point value. |
| `try_db_bind_text(stmt:int, index:int, value:str)` | `BoolResult` | Copy text, preserving embedded NUL. |
| `try_db_bind_bytes(stmt:int, index:int, value:[int])` | `BoolResult` | Copy binary data; empty bytes remain a BLOB, distinct from NULL. |
| `try_db_bind_null(stmt:int, index:int)` | `BoolResult` | Bind SQL NULL. |
| `try_db_step(stmt:int)` | `BoolResult` | On success, `value=true` means a current row; `false` means done. |
| `try_db_reset(stmt:int)` | `BoolResult` | Reset execution, retaining bindings; may report the previous execution error even though reset took effect. |
| `try_db_finalize(stmt:int)` | `BoolResult` | Release/invalidate the statement, including when reporting its previous error. |
| `try_db_columns(stmt:int)` | `IntResult` | Number of result columns. |
| `try_db_column_name(stmt:int, column:int)` | `StringResult` | Copy the column name; available before stepping. |
| `try_db_column_type(stmt:int, column:int)` | `StringResult` | Current value kind: `int`, `float`, `text`, `bytes`, or `null`. |
| `try_db_column_int(stmt:int, column:int)` | `IntResult` | Read an integer column without coercion. |
| `try_db_column_float(stmt:int, column:int)` | `FloatResult` | Read a finite float column without coercion. |
| `try_db_column_text(stmt:int, column:int)` | `StringResult` | Copy and validate UTF-8 text. |
| `try_db_column_bytes(stmt:int, column:int)` | `BytesResult` | Copy a BLOB into a byte array. |
| `try_db_changes(db:int)` | `IntResult` | SQLite's change count for the most recent modifying statement. |
| `try_db_last_id(db:int)` | `IntResult` | SQLite's last inserted row ID on this connection. |

Parameters are one-based; columns are zero-based. Bind external values through
prepared statements instead of interpolating them into SQL. Bindings use
SQLite's copying lifetime (`SQLITE_TRANSIENT`), so later collection or array
mutation cannot change a bound value. Unbound parameters follow SQLite's NULL
behavior. Binding is allowed only before execution or after reset.

After `step` reports done or an error, reset before another step. Value getters
require a current row and the exact SQLite storage type; they do not coerce
text to numbers or NULL to empty values. Text and byte results remain valid
after another step or finalization. SQL text rejects embedded NUL; text values
may contain it. Invalid handles, state, types, indices, SQL, and SQLite errors
all return `R015`; error messages include SQLite details where available.

Transactions are explicit: execute `BEGIN`, `COMMIT`, or `ROLLBACK`. Multi-
statement `exec` is not implicitly atomic. Finalize every statement before
closing its database. These lifecycle rules follow SQLite's
[step](https://www.sqlite.org/c3ref/step.html),
[binding](https://www.sqlite.org/c3ref/bind_blob.html), and
[close](https://www.sqlite.org/c3ref/close.html) interfaces.

See [the SQLite example](../examples/database.gly) for parameter binding and
cleanup on both successful and failed operations.

## CSV and Base64

| Call | Result | Contract |
| --- | --- | --- |
| `try_base64_encode(bytes:[int])` | `StringResult` | Standard Base64 alphabet with padding; byte validation uses `R009`. |
| `try_base64_decode(text:str)` | `BytesResult` | Strict padded Base64; malformed text uses `R016`. |
| `try_csv_parse(text:str)` | `StringsResult` | Validate and split a CSV document into serialized row strings. |
| `try_csv_row(row:str)` | `StringsResult` | Decode exactly one CSV row into fields; optional final line ending is accepted. |
| `csv_row(fields:[str])` | `str` | Quote each field and double embedded quotes; omit the final line ending. |
| `try_csv_write(rows:[str])` | `StringResult` | Validate rows and reserialize with CRLF endings. |

Base64 follows the standard alphabet and canonical padding rules in
[RFC 4648](https://www.rfc-editor.org/rfc/rfc4648.txt). Whitespace, URL-safe
alphabet variants, misplaced padding, and nonzero unused pad bits are rejected.

CSV uses the quoting rules described in
[RFC 4180](https://www.rfc-editor.org/rfc/rfc4180.txt), with UTF-8/control data
and LF line endings accepted as extensions. Commas delimit fields; quotes
inside quoted fields are doubled; quoted fields can contain newlines. Bare
CR outside quotes, stray quotes and text after a closing quote are rejected.
Whitespace in fields is preserved. Header rows receive no special treatment,
and row widths need not match. CSV failures use `R016`.

An empty CSV document has zero rows. An empty row has one empty field, and
`csv_row([])` also produces that empty row. A trailing comma adds an empty
field; a final line ending does not add a row. Parsed row fragments may retain
the source string; decoded fields are copied. CSV helpers process whole
strings, not incremental streams. They preserve field text without spreadsheet
formula transformations.
