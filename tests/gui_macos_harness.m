/* Exercise real AppKit controls and dispatch without human input.
 * Inclusion lets assertions inspect the private backend state. */
#include "../glyph/gui_macos.m"
#include <assert.h>
#include <setjmp.h>
#include <string.h>

static jmp_buf failed;
static void expect_error(const char *message, int line, int col) {
    assert(message && line == 7 && col == 9);
    longjmp(failed, 1);
}

int main(void) {
    g_gc_init();
    @autoreleasepool {
        g_str title = f_gc_title();
        glyph_ui_window(title.data, title.len, 360, 200, 7, 9);
        g_array views = f_gc_views();
        glyph_ui_widget(1, "Hello", 5, 20, 20, 320, 40, 0, 7, 9);
        glyph_ui_widget(2, "7", 1, 20, 90, 140, 44, 1, 7, 9);
        assert([ui_window.title isEqualToString:@"Glyph GUI test"]);
        assert(ui_widgets.count == 2);
        assert(ui_widgets[@1].frame.origin.y == 140);
        assert([((NSButton *)ui_widgets[@2]).keyEquivalent isEqualToString:@"7"]);
        glyph_ui_text(1, "Caf\xc3\xa9", 5, 7, 9);
        assert([ui_widgets[@1].stringValue isEqualToString:@"Café"]);
        for (int i = 0; i < 1000; i++) glyph_ui_number(1, i + 0.25, 7, 9);
        assert([ui_widgets[@1].stringValue isEqualToString:@"999.25"]);
        glyph_ui_text(2, "Seven", 5, 7, 9);
        assert([((NSButton *)ui_widgets[@2]).title isEqualToString:@"Seven"]);
        [(NSButton *)ui_widgets[@2] performClick:nil];
        assert(glyph_ui_next(7, 9) == 2);
        assert(ui_events.count == 0);
        f_gc_noise();
        GC_gcollect();
        assert(g_eq(((g_str *)views.data)[0], (g_str){"survives", 8}));
        assert([ui_window.title isEqualToString:@"Glyph GUI test"]);
        assert([ui_widgets[@1].stringValue isEqualToString:@"temporary-99"]);
        NSEvent *key = [NSEvent keyEventWithType:NSEventTypeKeyDown
            location:NSZeroPoint modifierFlags:0 timestamp:0
            windowNumber:ui_window.windowNumber context:nil
            characters:@"7" charactersIgnoringModifiers:@"7" isARepeat:NO keyCode:26];
        assert([ui_window performKeyEquivalent:key]);
        assert(glyph_ui_next(7, 9) == 2);
        glyph_ui_set_error(expect_error);
        if (!setjmp(failed)) {
            glyph_ui_widget(2, "duplicate", 9, 0, 0, 30, 30, 1, 7, 9);
            assert(!"duplicate widget accepted");
        }
        if (!setjmp(failed)) {
            glyph_ui_widget(3, "outside", 7, INT64_MAX, 0, 30, 30, 1, 7, 9);
            assert(!"out of bounds widget accepted");
        }
        if (!setjmp(failed)) {
            glyph_ui_text(99, "missing", 7, 7, 9);
            assert(!"missing widget accepted");
        }
        if (!setjmp(failed)) {
            glyph_ui_window("second", 6, 100, 100, 7, 9);
            assert(!"second window accepted");
        }
        [ui_window performClose:nil];
        assert(glyph_ui_next(7, 9) == 0);
        assert(!ui_window && !ui_widgets && !ui_events);
        glyph_ui_window("Reopened", 8, 120, 120, 7, 9);
        glyph_ui_close();
        glyph_ui_close();
        assert(glyph_ui_next(7, 9) == 0);
        puts("GUI lifecycle passed");
    }
}
