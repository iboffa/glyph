# Systems and text library

These typed builtins are available to ordinary Glyph programs as well as the
self-hosted compiler. They require no imports or `unsafe` blocks.

| Call | Result | Contract |
| --- | --- | --- |
| `concat(a:str, b:str)` | `str` | Allocate the concatenation. |
| `slice(s:str, start:int, end:int)` | `str` | Borrow a byte range `[start,end)`; bounds and UTF-8 character boundaries are checked. |
| `byte_at(s:str, index:int)` | `int` | Read one unsigned UTF-8 byte, with bounds checking. |
| `chr(code:int)` | `str` | Encode one Unicode scalar; reject surrogates/out-of-range values. |
| `join(parts:[str], count:int, separator:str)` | `str` | Join the first `count` entries in one allocation; reject an invalid count. |
| `str_i64(n:int)` | `str` | Decimal integer text. |
| `str_f64(n:f64)` | `str` | Number text with 17 significant digits. |
| `parse_i64(s:str)` | `int` | Parse complete decimal digits with an optional leading minus; no whitespace or leading plus. Overflow or invalid text traps. |
| `parse_f64(s:str)` | `f64` | Parse complete finite numeric text using the C numeric parser; finite underflow is allowed. |
| `valid_f64(s:str)` | `bool` | Whether the text can be parsed as a finite number. |
| `read_file(path:str)` | `str` | Read an entire seekable file as validated UTF-8. |
| `write_file(path:str, text:str)` | `void` | Create/truncate and write a file; check write/close errors. |
| `try_parse_i64(s:str)` | `IntResult` | Recoverable version of `parse_i64`. |
| `try_parse_f64(s:str)` | `FloatResult` | Recoverable version of `parse_f64`. |
| `try_read_file(path:str)` | `StringResult` | Recoverable version of `read_file`, including UTF-8 validation. |
| `try_write_file(path:str, text:str)` | `BoolResult` | Recoverable version of `write_file`; successful value is `true`. |
| `try_process(arguments:[str])` | `IntResult` | Recoverable launch/wait errors; successful value is the child's exit status. |
| `same_file(a:str, b:str)` | `bool` | True for identical path text, or existing paths referring to the same file identity. |
| `file_exists(path:str)` | `bool` | Whether the path currently names a regular file; follows symlinks, returns false for missing paths/directories. |
| `argc()` | `int` | Count arguments, excluding the executable. |
| `arg(index:int)` | `str` | Read a UTF-8 argument; index zero is the first program argument. |
| `getenv(name:str)` | `str` | Read a UTF-8 environment value; missing variables return an empty string. |
| `platform()` | `str` | `macos`, `windows`, or `posix` for other builds. |
| `process(arguments:[str])` | `int` | POSIX: execute/wait for a program; element zero names the executable. No shell parsing. |
| `eprint(text:str)` | `void` | Write text plus newline to standard error. |
| `exit(status:int)` | `void` | Exit using the low 8 bits of the status, running registered cleanup. |

`int` is the existing `i64` alias. Ordinary string lengths and `slice` offsets
count UTF-8 bytes, not characters. `slice` shares stable storage with its input.
Concatenated, formatted, joined, encoded and file-read strings belong to the same
nonmoving garbage-collected heap as arrays. Unreachable intermediate strings
can be reclaimed. Repeated concatenation still copies a quadratic number of
bytes; preallocate a parts array and use `join` for larger output. A small slice
keeps its entire backing string alive.

Strings may contain U+0000, but filesystem paths, environment names and child
process arguments reject embedded NUL. Text files and arguments must be valid
UTF-8; this API is not binary file I/O. `write_file` is a direct truncating write,
not an atomic replacement. `same_file` does not canonicalize nonexistent paths
or protect against concurrent filesystem changes.

On Windows, command-line arguments are converted from UTF-16 to UTF-8. Text
and binary file APIs convert paths back to UTF-16 and use wide-character file
operations, including file-existence and identity checks. They therefore support
Unicode paths independently of the active Windows code page.

`process` inherits standard streams and the environment, flushes parent output
before launch, and returns the child's exit code (or `128 + signal` when killed
by a signal). Launch/wait failures are runtime errors. Its initial implementation
supports POSIX systems; calling it on Windows reports an unsupported-operation
error. An argument containing spaces, quotes, `$()` or semicolons is passed as a
literal argument. Callers explicitly choosing a shell executable are responsible
for the resulting shell semantics.

Trapping failures use `R009` for text/encoding/conversion contracts and `R010` for
filesystem/process failures. Bounds errors remain `R003`; missing arguments use
`R005`. As with existing runtime traps, these report a source location and exit
with status 70.

## Recoverable failures

Use the `try_` functions when bad input or a failed operation should let the
application continue. They return ordinary value records without printing a
diagnostic or exiting. Both compilers provide these types without imports:

| Type | Fields, in constructor order |
| --- | --- |
| `IntResult` | `ok:bool`, `value:int`, `code:str`, `message:str` |
| `FloatResult` | `ok:bool`, `value:f64`, `code:str`, `message:str` |
| `StringResult` | `ok:bool`, `value:str`, `code:str`, `message:str` |
| `BoolResult` | `ok:bool`, `value:bool`, `code:str`, `message:str` |

On success, `ok` is true and `code`/`message` are empty. On failure, `ok` is
false, `code` is `R009` (text, encoding or embedded NUL) or `R010` (I/O or
process), and `message` describes the failed operation. The failed value is
zero, an empty string or false; always check `ok` before using it. Codes are
stable categories; message wording is not an API for branching. Results are
independent values and can be stored, passed through modules, or returned from
functions. They have ordinary record mutation and construction rules; the
compiler does not enforce checking `ok` or the relationship between fields.

```gly
positive text:str>IntResult
  parsed := try_parse_i64(text)
  if not parsed.ok
    ret parsed
  if parsed.value <= 0
    ret IntResult(false, 0, "positive", "expected a positive number")
  ret parsed

main>void
  for text:["bad", "0", "42"]
    result := positive(text)
    if result.ok
      print(result.value)
    else
      eprint(result.message)
  print("finished all inputs")
```

Applications can construct these records with their own error codes, or define
an ordinary record with the same convention for another payload type. There is
no built-in generic result type, exception unwinding, or automatic propagation syntax. Libraries can define `union Result[T,E]`; see [library abstractions](ABSTRACTIONS.md).
Return an unsuccessful result explicitly to propagate it.

The `try_` functions share parsing and I/O behavior with their trapping
counterparts. Embedded NUL in paths, numeric text or process arguments returns
an error. File handles close on I/O and encoding failures. A failed write can
still leave a truncated or partially written file; these calls are not
transactions. `try_process` returns `ok=true` when the child finishes even if
its exit status is nonzero; launch/wait errors and unsupported Windows process
execution return `ok=false`. Allocation failures and language safety traps
(such as overflow or bounds violations while evaluating arguments) remain
fatal. Existing functions retain their diagnostics and exit status 70.

```gly
main>void
  output := arg(0)
  text := join(["hello", "Glyph"], 2, " ")
  write_file(output, concat(text, "\n"))
  print(read_file(output))
```

## Binary and streaming I/O

Both compilers provide the following APIs. Binary values use existing `[int]`
arrays with elements in `0..255`; they do not use `str` and need not be UTF-8.
This first version uses eight bytes of array storage per byte, rather than a
new packed byte type. `BytesResult` has the usual `ok`, `value`, `code`, and
`message` fields, with `value:[int]`. On failure its value is an empty array.

| Call | Result | Contract |
| --- | --- | --- |
| `encode_utf8(text:str)` | `[int]` | Copy a string's UTF-8 bytes, including NUL. |
| `try_decode_utf8(bytes:[int])` | `StringResult` | Validate byte ranges and UTF-8, then copy into a string. |
| `try_read_bytes(path:str)` | `BytesResult` | Read to EOF without seeking; accepts binary files and readable pipes. |
| `try_write_bytes(path:str, bytes:[int])` | `BoolResult` | Validate all byte values before opening/truncating; write and close. |
| `try_open(path:str, mode:str)` | `IntResult` | Open in binary mode; `r` reads, `w` creates/truncates, `a` creates/appends. |
| `try_read(handle:int, count:int)` | `BytesResult` | Read up to a positive byte count; success with an empty array means EOF. |
| `try_write(handle:int, bytes:[int])` | `IntResult` | Validate every byte before writing; return the number accepted by the stream. |
| `try_flush(handle:int)` | `BoolResult` | Flush a writable stream; does not promise disk durability. |
| `try_close(handle:int)` | `BoolResult` | Close and invalidate the handle, including when close reports an error. |

Handles are process-local positive integers. IDs are never reused, so a closed
handle or a copy of one cannot access a subsequently opened file. Invalid,
closed, and wrong-direction handles produce recoverable `R010` failures.
Invalid modes and nonpositive read counts also return `R010`; byte-range,
UTF-8, and embedded-NUL path errors use `R009`.

Always close an opened handle on every ordinary exit path. Garbage collection
does not close files. These calls are blocking; a pipe read may wait for the
requested byte count or EOF. There is no seek, readiness polling, asynchronous
I/O, or standard-stream handle API yet. `try_read_bytes` grows its buffer until
EOF; `try_read` bounds each chunk's allocation by the requested count. Reads
return independent mutable arrays. An I/O error may consume bytes or leave a
partial write; failed result values are empty/zero, not a partial-byte count.
A successful write can still be followed by a flush or close failure. Empty
writes are valid. Allocation failures remain fatal, as with existing arrays.

```gly
main>void
  opened := try_open(arg(0), "r")
  if not opened.ok
    eprint(opened.message)
    exit(1)
  done := false
  while not done
    chunk := try_read(opened.value, 4096)
    if not chunk.ok
      eprint(chunk.message)
      done = true
    else
      if len(chunk.value) == 0
        done = true
      else
        print(len(chunk.value))
  closed := try_close(opened.value)
  if not closed.ok
    eprint(closed.message)
```

## JSON

JSON values are represented as validated JSON text in ordinary `str` values.
Parsing validates the complete input and returns its outer-whitespace-trimmed
text. Lookups return JSON text too: the string value `"hello"` remains quoted
until decoded with `try_json_string`. JSON `null` is a successful value distinct
from a missing key or failed lookup. Every reader validates its entire input,
so callers can pass raw text directly without a preceding parse call.

| Call | Result | Contract |
| --- | --- | --- |
| `try_json_parse(text:str)` | `StringResult` | Validate one complete JSON value; return its text without surrounding whitespace. |
| `try_json_kind(json:str)` | `StringResult` | `null`, `bool`, `number`, `string`, `array`, or `object`. |
| `try_json_get(json:str, key:str)` | `StringResult` | Look up an object member by its decoded key; last duplicate wins. |
| `try_json_at(json:str, index:int)` | `StringResult` | Look up a zero-based array element. |
| `try_json_len(json:str)` | `IntResult` | Count array elements or object members, including duplicate keys. |
| `try_json_keys(json:str)` | `StringsResult` | Decoded keys in input order, including duplicates; `value:[str]`. |
| `try_json_string(json:str)` | `StringResult` | Decode a JSON string, including escapes and surrogate pairs. |
| `json_quote(text:str)` | `str` | Encode ordinary text as a JSON string, escaping controls, quotes, and backslashes. |
| `try_json_array(values:[str])` | `StringResult` | Validate JSON values and serialize them in a new array. |
| `try_json_object(keys:[str], values:[str])` | `StringResult` | Quote ordinary-text keys and serialize validated JSON values; lengths must match. |

The parser follows the [RFC 8259 grammar](https://www.rfc-editor.org/rfc/rfc8259)
with a limit of 128 nested containers. It rejects lone Unicode surrogates to
preserve Glyph's UTF-8 string invariant, and rejects a leading byte-order mark.
Comments, trailing commas, non-JSON whitespace, leading-zero numbers, NaN,
and Infinity are not accepted. Malformed JSON, missing keys, wrong value kinds,
invalid indices, and excess nesting return `R012` without exiting. Error
messages are descriptive, not stable machine-readable subcodes or offsets.

Number lexemes are preserved without conversion to `f64`: large integers and
exponents therefore survive round-trips exactly. Convert a selected numeric
value explicitly with `try_parse_i64` or `try_parse_f64` when arithmetic is
needed, checking the result for representability. Use `str_i64` or `str_f64`
to construct numbers; the JSON constructors reject nonfinite float text.
Boolean and null values can be constructed with `"true"`, `"false"`, and
`"null"` fragments. Constructors validate fragments rather than treating them
as ordinary strings; use `json_quote` for text values.

This is a text-oriented API, not a persistent dynamic tree or automatic record
serializer. Each operation parses its input into a temporary collected tree;
repeated lookups reparse it. Returned text fragments may share the original
string storage. Serialization preserves supplied number text, object order,
and internal whitespace in supplied fragments; it is not canonical JSON.

See [the binary/JSON example](../examples/binary_json.gly) for a complete
write/read/parse round-trip with recoverable failures.

## Network, database and serialization services

See [Services](SERVICES.md) for TCP sockets, HTTP with verified TLS, SQLite
prepared statements, CSV and Base64. HTTP/SQLite programs require optional
system development libraries; the other builtins keep the existing toolchain.
