"""Conservative boundary and transitive worker-effect checks on the typed AST."""
from .syntax import Function, Diagnostic

NAMES = {'par_map', 'spawn', 'wait', 'task_status', 'task', 'channel', 'send', 'receive', 'close'}
# Explicit allowlist: additions require a runtime shared-state audit.
PURE = {'len', 'range', 'fill', 'clone', 'push', 'i64', 'f64', 'sum', 'count',
        'clock', 'list', 'map', 'set', 'concat', 'slice', 'byte_at', 'chr', 'join',
        'str_i64', 'str_f64', 'parse_i64', 'parse_f64', 'valid_f64',
        'try_parse_i64', 'try_parse_f64'}


def safe_type(typ, records, channels=False, seen=frozenset()):
    if typ.startswith("channel["):
        return channels and safe_type(typ[8:-1], records, False, seen)
    if typ in seen:
        return False
    if typ in {'i64', 'f64', 'bool', 'str'}:
        return True
    rec = records.get(typ)
    return rec is not None and all(safe_type(f.typ, records, channels, seen | {typ}) for f in rec.fields)


def analyze(checker):
    completed = set()
    def fail(node, message, code='G116'):
        raise Diagnostic(code, message, node.token)
    def function(f, mode):
        key = (id(f), mode)
        if key in completed:
            return
        completed.add(key)
        block(f.body, mode)
    def callback(e, mode):
        if e.kind == 'name' and isinstance(e.target, Function):
            function(e.target, mode)
        elif e.kind == 'lambda':
            for name, typ in e.target:
                if not safe_type(typ, checker.records, mode == 'task'):
                    fail(e, f'unsafe concurrent capture {name}: {typ}')
            expression(e.args[0], mode)
        else:
            fail(e, 'concurrent callback must be a named function or literal lambda; unknown effects')
    def expression(e, mode=None, handle=False, spawn=False):
        if e.typ.startswith('task[') and not (handle or spawn):
            fail(e, 'task handles cannot escape or be copied', 'G117')
        if e.kind == 'call' and e.value == 'par_map':
            callback(e.args[1], 'map')
        if e.kind == 'call' and e.value == 'spawn':
            if not spawn:
                fail(e, 'spawn requires a local declaration inside scope', 'G117')
            callback(e.args[0], 'task')
        if e.kind == 'lambda':
            for _, typ in e.target:
                if typ.startswith('task['):
                    fail(e, 'task handles cannot be captured', 'G117')
        if mode:
            if e.kind == 'call' and e.value == 'receive':
                callback(e.args[1], mode)
            if e.kind == 'invoke':
                callback(e.args[0], mode)
            if e.kind == 'call':
                if e.value in checker.signatures:
                    function(checker.signatures[e.value], mode)
                elif e.value not in checker.records and e.value not in PURE | NAMES:
                    fail(e, f'{e.value} is not permitted in workers')
                if mode == 'map' and e.value in {'spawn', 'wait', 'task_status', 'channel', 'send', 'receive', 'close'}:
                    fail(e, 'tasks are not permitted in parallel maps')
            if e.kind == 'method_call' and isinstance(e.target, Function):
                function(e.target, mode)
        for i, arg in enumerate(e.args):
            use_handle = e.kind == 'call' and e.value in {'wait', 'task_status'} and i == 0
            if use_handle and arg.kind != 'name':
                fail(arg, 'expected direct task handle binding', 'G117')
            expression(arg, mode, handle=use_handle)
    def block(body, mode=None, scope=0):
        for s in body:
            if mode and s.kind == 'unsafe':
                fail(s, 'unsafe blocks are not permitted in workers')
            for arg in s.args:
                spawn = s.kind == 'var' and arg.kind == 'call' and arg.value == 'spawn' and scope > 0
                expression(arg, mode, spawn=spawn)
            block(s.body, mode, scope + (s.kind == 'scope'))
            block(s.other, mode, scope)
    for f in checker.functions:
        block(f.body)
