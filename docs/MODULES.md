# File imports

Both the Python compiler and the self-hosted compiler support named imports:

```gly
import square, Counter from "./math.gly"

main>void
  counter := Counter.create(3)
  counter.add(square(4))
  print(counter.value)
```

See the runnable pair in [`examples/modules`](../examples/modules):

```sh
glyph run examples/modules/main.gly
build/selfhost/glyphc run examples/modules/main.gly -o build/modules-example
```

## Rules

- Put imports before function and record declarations. Each import occupies one
  line and names one or more functions or record types.
- Paths must be relative strings ending in `.gly`. Resolve them from the
  importing file's directory, not the process working directory. `..`, spaces,
  and Unicode filenames are supported. There is no package search path.
- Every top-level function and record declared in a module can be imported.
  There is no `export` keyword. Imported names are not automatically re-exported.
- Only explicitly imported names become visible in the importing file. A
  function can use its own module's helpers without exposing them to callers.
  Two modules may have helpers with the same name. Local variables retain their
  existing scoping and shadowing rules; record members retain their names.
- An import cannot overwrite another imported name or a local declaration.
  Duplicate names in one import are also errors. Aliases, wildcard imports, and
  module namespace expressions are not supported yet.
- The entry file defines `main`; imported modules must not define `main`.
  `glyph check library.gly` still checks for a complete program. To check a
  library, check an entry file that imports it.
- The compiler loads each file once, recognizing existing symlinks and hard
  links by file identity. Shared dependencies retain one record type identity.
  Relative imports inside an aliased file use the first path used to load it.
- Circular imports are rejected, including cycles through path aliases. Split
  shared declarations into a third file to remove a cycle.
- Record privacy still applies: importing a record does not grant access to
  its private fields or methods. Public methods can call their private helpers.
- All loaded declarations are type-checked, including unselected declarations.
  Imports are resolved at compile time; there is no runtime module loader or
  top-level executable initialization.

Programs are currently limited to 128 distinct files and 1 MiB of combined
UTF-8 source. Compiler and application heap storage are garbage collected. Compile-time and
runtime operation diagnostics identify the originating file. Output paths must
not overwrite any loaded source, including existing aliases.

`glyph fmt` formats imports without loading dependencies and edits only the
specified file. For Python embedding, use
`check(load_program(path))` with `glyph.modules.load_program` instead of
`check(parse(source))` when resolving a program's imports.

## Diagnostics

| Code | Meaning |
| --- | --- |
| `G400` | Invalid import path, missing module, or unresolved imports passed directly to the checker. |
| `G401` | Missing imported declaration, conflicting binding, or `main` in an imported module. |
| `G402` | Circular import. |
| `G005` | Source or file-count limit exceeded. |

Syntax, typing, and privacy errors retain their existing codes. The native
compiler still reports low-level read/encoding failures through the systems
runtime (`R009`/`R010`); missing files are diagnosed as `G400` at the import.
