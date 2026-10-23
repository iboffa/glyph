/* C ABI shared by generated code and the platform backend. No Glyph heap
 * values cross this boundary; strings are borrowed only for the call. */
#ifndef GLYPH_GUI_H
#define GLYPH_GUI_H
#include <stdint.h>
#include <stddef.h>
typedef void (*glyph_ui_error_fn)(const char *, int, int);
void glyph_ui_set_error(glyph_ui_error_fn);
void glyph_ui_window(const char *, int64_t, int64_t, int64_t, int, int);
void glyph_ui_widget(int64_t, const char *, int64_t, int64_t, int64_t,
                     int64_t, int64_t, int, int, int);
void glyph_ui_text(int64_t, const char *, int64_t, int, int);
void glyph_ui_number(int64_t, double, int, int);
int64_t glyph_ui_next(int, int);
void glyph_ui_close(void);
#endif
