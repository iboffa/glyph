"""Typed surface of the optional native GUI library.

Positive widget IDs belong to the single open window. gui_next returns a
clicked button's ID, or zero when the window closes.
"""

GUI_SIGNATURES = {
    "gui_window": (("str", "i64", "i64"), "void"),
    "gui_label": (("i64", "str", "i64", "i64", "i64", "i64"), "void"),
    "gui_button": (("i64", "str", "i64", "i64", "i64", "i64"), "void"),
    "gui_text": (("i64", "str"), "void"),
    "gui_number": (("i64", "f64"), "void"),
    "gui_next": ((), "i64"),
    "gui_close": ((), "void"),
}
