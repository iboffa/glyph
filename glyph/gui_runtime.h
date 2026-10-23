/* Included after runtime.h and gui.h only for programs using gui_* calls. */
static void g_gui_error(const char *message, int l, int c) {
    g_fail("R008", message, l, c);
}
static void g_gui_window(g_str title, int64_t w, int64_t h, int l, int c) {
    glyph_ui_set_error(g_gui_error);
    glyph_ui_window(title.data, title.len, w, h, l, c);
}
static void g_gui_label(int64_t id, g_str text, int64_t x, int64_t y,
                        int64_t w, int64_t h, int l, int c) {
    glyph_ui_set_error(g_gui_error);
    glyph_ui_widget(id, text.data, text.len, x, y, w, h, 0, l, c);
}
static void g_gui_button(int64_t id, g_str text, int64_t x, int64_t y,
                         int64_t w, int64_t h, int l, int c) {
    glyph_ui_set_error(g_gui_error);
    glyph_ui_widget(id, text.data, text.len, x, y, w, h, 1, l, c);
}
static void g_gui_text(int64_t id, g_str text, int l, int c) {
    glyph_ui_set_error(g_gui_error);
    glyph_ui_text(id, text.data, text.len, l, c);
}
static void g_gui_number(int64_t id, double value, int l, int c) {
    glyph_ui_set_error(g_gui_error);
    glyph_ui_number(id, value, l, c);
}
static int64_t g_gui_next(int l, int c) {
    glyph_ui_set_error(g_gui_error);
    return glyph_ui_next(l, c);
}
static void g_gui_close(int l, int c) {
    (void)l; (void)c;
    glyph_ui_close();
}
