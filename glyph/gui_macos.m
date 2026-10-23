/* Native, retained controls. All calls run on the program's main thread.
 * AppKit objects are ARC-managed; each operation/event drains its temporary
 * objects, independently of Glyph's collected heap. */
#import <AppKit/AppKit.h>
#include <stdio.h>
#include <stdlib.h>
#include "gui.h"

static glyph_ui_error_fn ui_error;
static NSWindow *ui_window;
static NSMutableDictionary<NSNumber *, NSControl *> *ui_widgets;
static NSMutableArray<NSNumber *> *ui_events;
static BOOL ui_started, ui_closed;

static void ui_fail(const char *message, int l, int c) {
    if (ui_error) ui_error(message, l, c);
    fprintf(stderr, "Glyph GUI: %s\n", message);
    exit(70);
}
static void ui_require_window(int l, int c) {
    if (!ui_window || ui_closed) ui_fail("GUI requires an open window", l, c);
}
static NSString *ui_string(const char *bytes, int64_t len, int l, int c) {
    if (len < 0) ui_fail("invalid GUI string length", l, c);
    NSString *s = [[NSString alloc] initWithBytes:bytes length:(NSUInteger)len
                                        encoding:NSUTF8StringEncoding];
    if (!s) ui_fail("GUI text must be valid UTF-8", l, c);
    return s;
}
static NSControl *ui_control(int64_t id, int l, int c) {
    ui_require_window(l, c);
    NSControl *control = ui_widgets[@(id)];
    if (!control) ui_fail("unknown GUI widget ID", l, c);
    return control;
}

@interface GlyphUIEvents : NSObject <NSWindowDelegate>
- (void)clicked:(NSButton *)sender;
- (void)quit:(id)sender;
@end
@implementation GlyphUIEvents
- (void)clicked:(NSButton *)sender {
    if (!ui_closed) [ui_events addObject:@(sender.tag)];
}
- (BOOL)windowShouldClose:(NSWindow *)sender {
    (void)sender;
    ui_closed = YES;
    [ui_events removeAllObjects];
    return YES;
}
- (void)quit:(id)sender {
    (void)sender;
    [ui_window performClose:nil];
}
@end
static GlyphUIEvents *ui_delegate;

void glyph_ui_set_error(glyph_ui_error_fn handler) { ui_error = handler; }

void glyph_ui_close(void) {
    @autoreleasepool {
        ui_closed = YES;
        ui_window.delegate = nil;
        [ui_window close];
        ui_window = nil;
        ui_widgets = nil;
        ui_events = nil;
    }
}

void glyph_ui_window(const char *title, int64_t len, int64_t w, int64_t h, int l, int c) {
    @autoreleasepool {
        if (ui_window && !ui_closed) ui_fail("only one GUI window may be open", l, c);
        if (w < 1 || h < 1 || w > 16384 || h > 16384)
            ui_fail("GUI window dimensions must be between 1 and 16384", l, c);
        glyph_ui_close();
        [NSApplication sharedApplication];
        if (!ui_started) {
            [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
            ui_delegate = [GlyphUIEvents new];
            NSMenu *menu = [NSMenu new];
            NSMenuItem *appItem = [NSMenuItem new];
            [menu addItem:appItem];
            NSMenu *appMenu = [NSMenu new];
            NSMenuItem *quit = [[NSMenuItem alloc] initWithTitle:@"Quit"
                action:@selector(quit:) keyEquivalent:@"q"];
            quit.target = ui_delegate;
            [appMenu addItem:quit];
            appItem.submenu = appMenu;
            NSApp.mainMenu = menu;
            [NSApp finishLaunching];
            atexit(glyph_ui_close);
            ui_started = YES;
        }
        ui_closed = NO;
        ui_widgets = [NSMutableDictionary new];
        ui_events = [NSMutableArray new];
        ui_window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, w, h)
            styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
                      NSWindowStyleMaskMiniaturizable
            backing:NSBackingStoreBuffered defer:NO];
        ui_window.releasedWhenClosed = NO;
        ui_window.title = ui_string(title, len, l, c);
        ui_window.delegate = ui_delegate;
        [ui_window center];
        [ui_window makeKeyAndOrderFront:nil];
        [NSApp activateIgnoringOtherApps:YES];
    }
}

void glyph_ui_widget(int64_t id, const char *text, int64_t len,
                     int64_t x, int64_t y, int64_t w, int64_t h,
                     int button, int l, int c) {
    @autoreleasepool {
        ui_require_window(l, c);
        if (id <= 0 || ui_widgets[@(id)]) ui_fail("GUI widget IDs must be positive and unique", l, c);
        if (ui_widgets.count >= 4096) ui_fail("GUI window widget limit reached", l, c);
        NSSize size = ui_window.contentView.bounds.size;
        /* Subtract after validating positive bounded sizes to avoid overflow. */
        if (w < 1 || h < 1 || w > size.width || h > size.height ||
            x < 0 || y < 0 || x > size.width - w || y > size.height - h)
            ui_fail("GUI widget rectangle must fit inside the window", l, c);
        NSRect frame = NSMakeRect(x, size.height - y - h, w, h);
        NSString *label = ui_string(text, len, l, c);
        NSControl *control;
        if (button) {
            NSButton *b = [[NSButton alloc] initWithFrame:frame];
            b.title = label;
            b.bezelStyle = NSBezelStyleRegularSquare;
            b.buttonType = NSButtonTypeMomentaryPushIn;
            b.font = [NSFont systemFontOfSize:20];
            b.tag = (NSInteger)id;
            b.target = ui_delegate;
            b.action = @selector(clicked:);
            /* Native keyboard equivalents accompany the visible buttons. */
            if (label.length == 1) {
                b.keyEquivalent = [label isEqualToString:@"="] ? @"\r" : label.lowercaseString;
                b.keyEquivalentModifierMask = 0;
            }
            control = b;
        } else {
            NSTextField *field = [[NSTextField alloc] initWithFrame:frame];
            field.editable = NO;
            field.selectable = YES;
            field.bezeled = NO;
            field.drawsBackground = NO;
            field.font = [NSFont monospacedDigitSystemFontOfSize:26 weight:NSFontWeightRegular];
            field.alignment = NSTextAlignmentRight;
            field.stringValue = label;
            control = field;
        }
        ui_widgets[@(id)] = control;
        [ui_window.contentView addSubview:control];
    }
}

void glyph_ui_text(int64_t id, const char *text, int64_t len, int l, int c) {
    @autoreleasepool {
        NSControl *control = ui_control(id, l, c);
        NSString *value = ui_string(text, len, l, c);
        if ([control isKindOfClass:[NSButton class]]) {
            /* Keyboard shortcuts remain those assigned at construction. */
            ((NSButton *)control).title = value;
        } else {
            control.stringValue = value;
        }
    }
}

void glyph_ui_number(int64_t id, double value, int l, int c) {
    char buffer[64];
    int len = snprintf(buffer, sizeof buffer, "%.12g", value);
    glyph_ui_text(id, buffer, len, l, c);
}

int64_t glyph_ui_next(int l, int c) {
    if (!ui_started) ui_fail("gui_next requires a window to have been opened", l, c);
    while (!ui_closed) {
        @autoreleasepool {
            [ui_window displayIfNeeded];
            [NSApp updateWindows];
            if (ui_events.count) {
                int64_t result = ui_events[0].longLongValue;
                [ui_events removeObjectAtIndex:0];
                return result;
            }
            /* Block when idle; dequeue one event and drain its temporary
             * allocations before waiting again. Window close wakes this loop. */
            NSEvent *event = [NSApp nextEventMatchingMask:NSEventMaskAny
                untilDate:[NSDate distantFuture] inMode:NSDefaultRunLoopMode dequeue:YES];
            if (event) [NSApp sendEvent:event];
        }
    }
    glyph_ui_close();
    return 0;
}
