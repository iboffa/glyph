"""Small, typed systems library used by ordinary programs and the compiler."""
RESULT_TYPES = {"IntResult": "i64", "FloatResult": "f64", "StringResult": "str", "BoolResult": "bool",
                "BytesResult": "[i64]", "StringsResult": "[str]"}


def result_records():
    """Fresh record metadata; layouts are supplied by std_runtime.h."""
    from .syntax import Field, Record, Token
    token = Token("", 1, 1, 1)
    return {name: Record(name, token, [Field(n, t, token) for n, t in
            (("ok", "bool"), ("value", typ), ("code", "str"), ("message", "str"))])
            for name, typ in RESULT_TYPES.items()}


STD_SIGNATURES = {
    "encode_utf8": (("str",), "[i64]"),
    "try_decode_utf8": (("[i64]",), "StringResult"),
    "try_read_bytes": (("str",), "BytesResult"),
    "try_write_bytes": (("str", "[i64]"), "BoolResult"),
    "try_open": (("str", "str"), "IntResult"),
    "try_read": (("i64", "i64"), "BytesResult"),
    "try_write": (("i64", "[i64]"), "IntResult"),
    "try_flush": (("i64",), "BoolResult"),
    "try_close": (("i64",), "BoolResult"),
    "try_json_parse": (("str",), "StringResult"),
    "try_json_kind": (("str",), "StringResult"),
    "try_json_get": (("str", "str"), "StringResult"),
    "try_json_at": (("str", "i64"), "StringResult"),
    "try_json_len": (("str",), "IntResult"),
    "try_json_keys": (("str",), "StringsResult"),
    "try_json_string": (("str",), "StringResult"),
    "json_quote": (("str",), "str"),
    "try_json_array": (("[str]",), "StringResult"),
    "try_json_object": (("[str]", "[str]"), "StringResult"),
    "try_parse_i64": (("str",), "IntResult"),
    "try_parse_f64": (("str",), "FloatResult"),
    "try_read_file": (("str",), "StringResult"),
    "try_write_file": (("str", "str"), "BoolResult"),
    "try_process": (("[str]",), "IntResult"),
    "concat": (("str", "str"), "str"),
    "slice": (("str", "i64", "i64"), "str"),
    "byte_at": (("str", "i64"), "i64"),
    "chr": (("i64",), "str"),
    "join": (("[str]", "i64", "str"), "str"),
    "str_i64": (("i64",), "str"),
    "str_f64": (("f64",), "str"),
    "parse_i64": (("str",), "i64"),
    "parse_f64": (("str",), "f64"),
    "valid_f64": (("str",), "bool"),
    "read_file": (("str",), "str"),
    "write_file": (("str", "str"), "void"),
    "same_file": (("str", "str"), "bool"),
    "file_exists": (("str",), "bool"),
    "arg": (("i64",), "str"),
    "argc": ((), "i64"),
    "getenv": (("str",), "str"),
    "platform": ((), "str"),
    "process": (("[str]",), "i64"),
    "eprint": (("str",), "void"),
    "exit": (("i64",), "void"),
}
