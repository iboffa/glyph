#ifndef GLYPH_RUNTIME_H
#define GLYPH_RUNTIME_H
#define GLYPH_GC 1
#ifndef GC_NOT_DLL
#define GC_NOT_DLL
#endif
#include <gc.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <errno.h>
#include <math.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#endif

typedef struct { const char *data; int64_t len; } g_str;
typedef struct { void *data; int64_t len; } g_array;
static bool g_gc_stress;
static int g_argc;
static char **g_argv;
static const char *g_file_json = G_FILE_JSON;

static void g_gc_init(void) {
    GC_set_all_interior_pointers(1);
    GC_INIT();
    const char *stress = getenv("GLYPH_GC_STRESS");
    g_gc_stress = stress && !strcmp(stress, "1");
}
static void g_fail(const char *code, const char *message, int line, int col) {
    fputs("{\"file\":", stderr);
    fputs(g_file_json, stderr);
    fputc(',', stderr);
    fprintf(stderr, "\"code\":\"%s\",\"severity\":\"error\",\"message\":\"%s\",\"span\":{\"start\":{\"line\":%d,\"column\":%d},\"end\":{\"line\":%d,\"column\":%d}}}\n", code, message, line, col, line, col + 1);
    exit(70);
}
static int64_t g_add(int64_t a, int64_t b, int l, int c) {
    int64_t r; if (__builtin_add_overflow(a,b,&r)) g_fail("R001","integer overflow",l,c); return r;
}
static int64_t g_sum_i64(g_array array, int64_t s, int l, int c) {
    const int64_t *a = array.data;
    int64_t i = 0;
    const int64_t slack = INT64_C(549755813888); /* 256 * 2^31 */
    for (; i <= array.len - 256; i += 256) {
        if (s < INT64_MIN + slack || s > INT64_MAX - slack) break;
        uint64_t bits = 0, range = 0;
        for (int j = 0; j < 256; ++j) {
            uint64_t u = (uint64_t)a[i + j];
            bits += u;
            range |= u + UINT64_C(2147483648);
        }
        /*
         * The OR guard proves every element fits signed i32. The accumulator
         * headroom then proves every left-to-right prefix fits i64, so the
         * vectorizable unsigned sum has the exact checked result.
         * Stop speculating on the first failure: scan at most one failed block,
         * then execute the entire remaining suffix in the original order.
         */
        if (range > UINT32_MAX) break;
        uint64_t result = (uint64_t)s + bits;
        memcpy(&s, &result, sizeof s);
    }
    for (; i < array.len; ++i) s = g_add(s, a[i], l, c);
    return s;
}
static int64_t g_sub(int64_t a, int64_t b, int l, int c) {
    int64_t r; if (__builtin_sub_overflow(a,b,&r)) g_fail("R001","integer overflow",l,c); return r;
}
static int64_t g_mul(int64_t a, int64_t b, int l, int c) {
    int64_t r; if (__builtin_mul_overflow(a,b,&r)) g_fail("R001","integer overflow",l,c); return r;
}
static int64_t g_div(int64_t a, int64_t b, int l, int c) {
    if (!b) g_fail("R002","integer division by zero",l,c);
    if (a==INT64_MIN && b==-1) g_fail("R001","integer overflow",l,c);
    return a/b;
}
static int64_t g_mod(int64_t a, int64_t b, int l, int c) {
    if (!b) g_fail("R002","integer remainder by zero",l,c);
    if (a==INT64_MIN && b==-1) g_fail("R001","integer overflow",l,c);
    return a%b;
}
static g_array g_allocate(int64_t n, size_t size, int l, int c, bool atomic) {
    if (!size || n<0 || (uint64_t)n>SIZE_MAX/size) g_fail("R004","invalid allocation size",l,c);
    size_t bytes = (n ? (size_t)n : 1) * size;
    if (g_gc_stress) GC_gcollect();
    void *data = atomic ? GC_malloc_atomic(bytes) : GC_malloc(bytes);
    if (!data) g_fail("R004","allocation failed",l,c);
    /* Atomic allocations are not cleared by BDWGC. Preserve zero initialization. */
    if (atomic) memset(data, 0, bytes);
    return (g_array){data,n};
}
static g_array g_new(int64_t n, size_t size, int l, int c) {
    return g_allocate(n,size,l,c,false);
}
static g_array g_new_atomic(int64_t n, size_t size, int l, int c) {
    return g_allocate(n,size,l,c,true);
}
static int64_t g_index(g_array a, int64_t i, int l, int c) {
    if (i<0 || i>=a.len) g_fail("R003","array index out of bounds",l,c);
    return i;
}
static g_array g_clone(g_array a, size_t size, int l, int c) {
    g_array b=g_new(a.len,size,l,c); memcpy(b.data,a.data,(size_t)a.len*size); return b;
}
static g_array g_clone_atomic(g_array a, size_t size, int l, int c) {
    g_array b=g_new_atomic(a.len,size,l,c); memcpy(b.data,a.data,(size_t)a.len*size); return b;
}
static g_array g_range(int64_t n, int l, int c) {
    g_array a=g_new_atomic(n,sizeof(int64_t),l,c);
    for(int64_t i=0;i<n;i++) ((int64_t*)a.data)[i]=i;
    return a;
}
static bool g_eq(g_str a, g_str b) { return a.len==b.len && !memcmp(a.data,b.data,(size_t)a.len); }
static void g_print_i64(int64_t x) { printf("%lld\n",(long long)x); }
static void g_print_f64(double x) { printf("%.17g\n",x); }
static void g_print_bool(bool x) { puts(x ? "true" : "false"); }
static void g_print_str(g_str x) { fwrite(x.data,1,(size_t)x.len,stdout); putchar('\n'); }
static int64_t g_argi(int64_t i, int l, int c) {
    if (i<0 || i >= (int64_t)g_argc-1) g_fail("R005","missing integer argument",l,c);
    char *s=g_argv[i+1], *end;
    if (!*s || (*s!='-' && (*s<'0' || *s>'9'))) g_fail("R005","invalid integer argument",l,c);
    errno=0; long long x=strtoll(s,&end,10);
    if (errno || *end) g_fail("R005","invalid integer argument",l,c);
    return (int64_t)x;
}
static double g_clock(void) {
#ifdef _WIN32
    LARGE_INTEGER now, freq; QueryPerformanceCounter(&now); QueryPerformanceFrequency(&freq);
    return (double)now.QuadPart/(double)freq.QuadPart;
#else
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC,&ts); return ts.tv_sec+ts.tv_nsec*1e-9;
#endif
}
static int64_t g_to_i64(double x, int l, int c) {
    if (!isfinite(x) || x < -9223372036854775808.0 || x >= 9223372036854775808.0)
        g_fail("R006","float outside i64 range",l,c);
    return (int64_t)x;
}
#endif
