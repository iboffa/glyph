# Bundled Boehm–Demers–Weiser collector

`bdwgc/` contains an unmodified source subset of BDWGC 8.2.12, compiled
through its upstream `extra/gc.c` amalgamation. `UPSTREAM.json` records the
release URL, archive SHA-256, and individual file hashes.

Copyright notices and permissions are retained in each upstream file. See
`bdwgc/README.md`, “Copyright & Warranty”, for the upstream licensing overview.
These sources retain their upstream licenses, independently of Glyph.

Glyph builds a static, single-threaded collector with interior-pointer support
and compiler-provided atomic primitives. No separate GC installation, download,
configure script, or Python runtime in the resulting executable is required.
Python caches the collector object; the native compiler compiles the bundled
amalgamation alongside the generated C. Generated C needs the bundled include
directory and a collector object when compiled outside either Glyph driver.
