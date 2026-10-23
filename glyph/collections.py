"""Builtin collection types and their method signatures (with concrete scalar, record and function value arguments)."""
KINDS = {'list', 'map', 'set'}
KEYS = {'i64', 'bool', 'str'}


def collection_type(typ):
    return any(typ.startswith(kind + '[') for kind in KINDS)


def parts(typ):
    kind, args = typ.split('[', 1)
    from .abstractions import split_types
    return kind, split_types(args[:-1])


def method_signature(typ, name):
    kind, args = parts(typ)
    key, value = args[0], args[-1]
    common = {'clear': ([], 'void')}
    if kind == 'list':
        common |= {'append': ([value], 'void'), 'get': (['i64'], value),
                   'set': (['i64', value], 'void'), 'pop': ([], value),
                   'remove': (['i64'], value), 'to_array': ([], f'[{value}]')}
    else:
        common |= {'contains': ([key], 'bool'), 'remove': ([key], 'bool'),
                   'keys': ([], f'[{key}]')}
        if kind == 'map':
            common |= {'put': ([key, value], 'void'), 'get': ([key], value),
                       'get_or': ([key, value], value), 'values': ([], f'[{value}]')}
        else:
            common |= {'add': ([key], 'bool'), 'to_array': ([], f'[{key}]')}
    return common.get(name)
