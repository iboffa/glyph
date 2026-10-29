"""Restricted explicit allocation domains and affine local buffer checking.

Only primitive layouts are supported. No managed reference can enter external
storage, so no unregistered collector roots can be hidden in malloc memory.
"""
from .syntax import Diagnostic
from .analysis import READ, SCALAR

NAMES = {'arena_fill', 'owned_fill', 'free', 'move', 'managed'}

def validate(checker):
    def fail(n, message):
        raise Diagnostic('G121', message, n.token)
    for f in checker.functions:
        # Owners are inferred locals only; validate_type rejects them in signatures.
        def block(body, regions, owners, arena=False, borrowed=frozenset()):
            regions, owners = dict(regions), dict(owners)
            inherited = set(owners)
            def expr(e, parent=None, pos=0, special=False):
                if e.kind == 'lambda' and any(n in regions or n in owners for n, _ in e.target):
                    fail(e, 'arena/borrowed/owned storage cannot be captured')
                if e.kind == 'name':
                    if e.value in owners:
                        if not special or owners[e.value] != 'live' or e.value in borrowed:
                            fail(e, 'owned buffer requires a live, unborrowed move/free/borrow operand')
                    if e.value in regions:
                        allowed = parent and (parent.kind == 'index' and pos == 0 or
                            parent.kind == 'call' and parent.value in READ | {'managed', 'clone'} and parent.value not in checker.signatures or
                            parent.kind in {'fold', 'for'} and pos == 0)
                        if not allowed:
                            fail(e, 'arena/borrowed array cannot escape, alias, enter a closure, or expose a pointer; use managed(array)')
                if e.kind == 'call':
                    if e.value == 'arena_fill' and (not arena or not special):
                        fail(e, 'arena_fill requires an arena block')
                    if e.value in {'owned_fill', 'move', 'free'} and not special:
                        fail(e, 'owned_fill/move require a local initializer; free requires a standalone statement')
                for i, a in enumerate(e.args):
                    expr(a, e, i, special=e.kind == 'call' and e.value in {'move', 'free'} and special)
            for s in body:
                if s.kind == 'var':
                    e = s.args[0]; name, typ = s.value
                    own = typ.startswith('buffer[')
                    expr(e, special=own or e.kind == 'call' and e.value == 'arena_fill')
                    if own:
                        if e.kind != 'call' or e.value not in {'owned_fill', 'move'}:
                            fail(e, 'owned buffers cannot be copied')
                        if e.value == 'move':
                            src = e.args[0]
                            if src.kind != 'name':
                                fail(src, 'move requires a direct owner binding')
                            owners[src.value] = 'moved'
                        owners[name] = 'live'
                    elif e.kind == 'call' and e.value == 'arena_fill':
                        regions[name] = 'arena'
                elif s.kind == 'borrow':
                    e = s.args[0]
                    if e.kind != 'name' or e.value not in owners or owners[e.value] != 'live' or e.value in borrowed:
                        fail(e, 'borrow requires a live unborrowed owner')
                    block(s.body, {**regions, s.value: 'borrow'}, owners, arena, borrowed | {e.value})
                elif s.kind == 'expr' and s.args[0].kind == 'call' and s.args[0].value == 'free':
                    e = s.args[0]
                    expr(e, special=True)
                    if e.args[0].kind != 'name':
                        fail(e, 'free requires a direct owner binding')
                    owners[e.args[0].value] = 'freed'
                elif s.kind == 'arena':
                    block(s.body, regions, owners, True, borrowed)
                else:
                    for a in s.args:
                        expr(a, s)
                    if s.kind == 'set' and s.args[0].kind == 'name' and s.args[0].value in regions:
                        fail(s, 'region bindings cannot be reassigned')
                    for child in (s.body, s.other):
                        if child:
                            block(child, regions, owners, arena, borrowed)
            # Outer owners cannot change conditionally/in loops/inside borrows.
            # A move at top level is allowed; each child gets its own copy.
            return {k: owners[k] for k in inherited}
        # Child scopes may only consume owners they declare themselves.
        # Enforce by counting free/move operations against lexical depth.
        def lifetimes(body, declared=frozenset()):
            local = set()
            for s in body:
                if s.kind == 'var' and s.value[1].startswith('buffer['):
                    e = s.args[0]
                    if e.kind == 'call' and e.value == 'move' and e.args[0].value not in local:
                        fail(e, 'move of an outer owner across a control-flow boundary is unsupported')
                    local.add(s.value[0])
                if s.kind == 'expr' and s.args[0].kind == 'call' and s.args[0].value == 'free':
                    if s.args[0].args[0].value not in local:
                        fail(s, 'free of an outer owner across a control-flow boundary is unsupported')
                lifetimes(s.body, declared | local)
                lifetimes(s.other, declared | local)
        block(f.body, {}, {})
        lifetimes(f.body)
