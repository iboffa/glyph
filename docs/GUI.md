# Glyph GUI

Glyph's first GUI library provides native windows, labels and buttons. Application
state and event handling stay in Glyph. The bundled macOS backend uses AppKit
through a small C ABI; it does not embed Python in the executable.

This is a minimal retained-control UI library, not a canvas or a complete desktop
framework. It currently supports **macOS only**. Windows and Linux backends, custom
drawing, text entry, automatic layout, multiple simultaneous windows and general
foreign-function declarations are not implemented.

## Run

Install Glyph as described in the README. GUI builds also require Apple's Xcode
or Command Line Tools (`xcrun clang` and the macOS SDK).

```sh
python -m glyph run examples/gui_hello.gly
python -m glyph run examples/calculator.gly
```

There is no GUI build flag or additional package to install. The compiler detects
calls to `gui_*` functions and links the bundled Objective-C backend against
AppKit. It uses Apple Clang for these builds; ordinary console programs continue
to use the existing Zig/Clang toolchain and do not link a GUI framework. GUI
source can be checked and formatted on any platform; building it on an unsupported
platform reports `G203`.

## First program

```gly
main>void
  gui_window("Hello", 320, 160)
  gui_label(1, "Hello, Glyph!", 20, 20, 280, 40)
  gui_button(2, "Close", 20, 90, 280, 44)
  event := gui_next()
  while event != 0
    if event == 2
      gui_close()
    event = gui_next()
```

Create controls once, then wait for events and update their contents. `gui_next()`
blocks while idle and continues to dispatch native window events. It returns a
clicked button's positive ID, or `0` after the window closes. Closing with the
window button or Command-Q follows the same path. The library needs no callbacks,
closures, threads, or `unsafe` blocks.

Glyph has no imports yet: these functions are reserved, typed builtins backed by
an optional native library. This surface is intentionally small; it is not a
general C FFI or module system.

## API

`int` means `i64`. Coordinates and sizes are integer logical points, with the
origin at the top left of the window's content area. Window sizes exclude the
title bar. Native controls scale for Retina displays and follow system appearance.

| Function | Result | Behavior |
| --- | --- | --- |
| `gui_window(title:str, width:int, height:int)` | `void` | Open one fixed-size window. Dimensions must be 1–16384. |
| `gui_label(id:int, text:str, x:int, y:int, width:int, height:int)` | `void` | Create a selectable, non-editable, right-aligned label. |
| `gui_button(id:int, text:str, x:int, y:int, width:int, height:int)` | `void` | Create a native button; a click queues its ID. |
| `gui_text(id:int, text:str)` | `void` | Replace a label's text or a button's title. |
| `gui_number(id:int, value:f64)` | `void` | Display a number using 12 significant digits; convert integers with `f64(n)`. |
| `gui_next()` | `int` | Wait for the next button ID, or return `0` when closed. |
| `gui_close()` | `void` | Close and release the current window and its controls. Safe to call repeatedly. |

Widget IDs must be positive and unique across labels and buttons in the current
window. Up to 4096 controls are allowed. Rectangles must have positive sizes and
fit entirely inside the window. IDs can be reused after closing and reopening.
There is no per-widget deletion in this version.

Single-character button titles get an unmodified keyboard equivalent at creation;
letters use lowercase, and `=` uses Return. Changing a button's title preserves
its original shortcut. Multi-character titles have no automatic shortcut.
Duplicate shortcuts should be avoided.

Invalid lifecycle calls, IDs, rectangles or dimensions produce runtime diagnostic
`R008` with the Glyph call's source location, then exit with status 70. Call
`gui_window` before creating/updating controls or first calling `gui_next`.
After an opened window closes, `gui_next` returns `0` until another window opens.
Only one window may be open at a time.

The backend copies supplied UTF-8 text into native objects. Updating a label does
not retain Glyph heap pointers after the call. Native controls live until window
close; temporary native objects are drained per operation/event. Normal program
exit also closes the window. Application arrays and strings are garbage collected
during execution. Repeated `push` still copies an array and can be costly in an
event loop; collection can introduce pauses. Glyph heap access remains on the
main thread. The macOS collector uses upstream `LARGE_CONFIG` to accommodate
the many static root ranges loaded by AppKit.

## Calculator example

The example supports the four arithmetic operations, decimal entry, sign change,
clear, and division-by-zero/large-result error display. It evaluates operations
left to right, supports replacing a pending operator, and accepts a new number
after equals. Repeated equals is a no-op. Input is limited to 15 digits; the
display uses 12 significant digits and shows the numeric value, so a trailing
decimal point or trailing fractional zero is not preserved visually. Results
outside ±1e100 display `Error`; clear resets the state.

The `Calculator` record is independent of the interface. Tests exercise that same
record with scripted button IDs without opening a window. All arithmetic is
binary `f64`, not decimal arithmetic.

## Verification

```sh
python -m unittest discover -s tests -v
# Run real AppKit control/keyboard/lifecycle tests in a macOS desktop session:
GLYPH_TEST_GUI=1 python -m unittest discover -s tests -p test_gui.py -v
```

The normal suite checks signatures, reserved names, formatting, optional linking,
unsupported-platform diagnostics, calculator behavior, and (on macOS) native
builds and pre-window runtime errors. The opt-in desktop test creates real native
controls, dispatches button/keyboard actions, checks text and geometry, rejects
invalid operations, and verifies close/reopen cleanup. It opens brief test windows.

Backend event loop reference:
[Apple's NSApplication event dispatch API](https://developer.apple.com/documentation/appkit/nsapplication/nextevent(matching:until:inmode:dequeue:)).
