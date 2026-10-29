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
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <shellapi.h>
#endif

typedef struct { const char *data; int64_t len; } g_str;
typedef struct { void *data; int64_t len; } g_array;
static bool g_gc_stress;
#ifdef GLYPH_ALLOC_STATS
#include <stdatomic.h>
static _Atomic uint64_t g_alloc_count[3], g_alloc_bytes[3];
static void g_stats_report(void) {
    fprintf(stderr, "GLYPH_MEMORY {\"gc_count\":%llu,\"gc_bytes\":%llu,\"arena_count\":%llu,\"arena_bytes\":%llu,\"owned_count\":%llu,\"owned_bytes\":%llu,\"heap_bytes\":%zu,\"free_bytes\":%zu,\"collections\":%lu}\n",
        (unsigned long long)atomic_load(&g_alloc_count[0]), (unsigned long long)atomic_load(&g_alloc_bytes[0]),
        (unsigned long long)atomic_load(&g_alloc_count[1]), (unsigned long long)atomic_load(&g_alloc_bytes[1]),
        (unsigned long long)atomic_load(&g_alloc_count[2]), (unsigned long long)atomic_load(&g_alloc_bytes[2]),
        GC_get_heap_size(), GC_get_free_bytes(), (unsigned long)GC_get_gc_no());
}
#define G_ALLOC_RECORD(domain, bytes) do { atomic_fetch_add_explicit(&g_alloc_count[domain], 1, memory_order_relaxed); atomic_fetch_add_explicit(&g_alloc_bytes[domain], bytes, memory_order_relaxed); } while(0)
#else
#define G_ALLOC_RECORD(domain, bytes) ((void)0)
#endif
#ifdef GLYPH_GC_TIMING
/* Collector callbacks run under its allocation lock. No allocation or I/O here.
   Collection duration and time with the world stopped are distinct metrics. */
#define G_GC_SAMPLES 4096
static double g_gc_collection[G_GC_SAMPLES], g_gc_pause[G_GC_SAMPLES];
static size_t g_gc_collection_count, g_gc_pause_count;
static double g_gc_begin, g_gc_stop, g_gc_cpu_begin, g_gc_cpu_total;
static double g_gc_time(bool cpu) {
#ifndef _WIN32
    struct timespec t;
    clock_gettime(cpu ? CLOCK_THREAD_CPUTIME_ID : CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
#else
    (void)cpu; return 0; /* Driver documents unsupported timing on Windows. */
#endif
}
static void g_gc_event(GC_EventType event) {
    if (event == GC_EVENT_START) { g_gc_begin = g_gc_time(false); g_gc_cpu_begin = g_gc_time(true); }
    if (event == GC_EVENT_END) {
        double elapsed = g_gc_time(false) - g_gc_begin;
        g_gc_cpu_total += g_gc_time(true) - g_gc_cpu_begin;
        if (g_gc_collection_count < G_GC_SAMPLES) g_gc_collection[g_gc_collection_count] = elapsed;
        ++g_gc_collection_count;
    }
    if (event == GC_EVENT_POST_STOP_WORLD) g_gc_stop = g_gc_time(false);
    if (event == GC_EVENT_PRE_START_WORLD) {
        if (g_gc_pause_count < G_GC_SAMPLES) g_gc_pause[g_gc_pause_count] = g_gc_time(false) - g_gc_stop;
        ++g_gc_pause_count;
    }
}
static void g_gc_timing_report(void) {
    fprintf(stderr, "GLYPH_GC {\"collector_thread_cpu_s\":%.9g,\"collection_count\":%zu,\"pause_count\":%zu,\"collection_s\":[", g_gc_cpu_total, g_gc_collection_count, g_gc_pause_count);
    for (size_t i=0; i<g_gc_collection_count && i<G_GC_SAMPLES; ++i) fprintf(stderr, "%s%.9g", i ? "," : "", g_gc_collection[i]);
    fputs("],\"stop_world_s\":[", stderr);
    for (size_t i=0; i<g_gc_pause_count && i<G_GC_SAMPLES; ++i) fprintf(stderr, "%s%.9g", i ? "," : "", g_gc_pause[i]);
    fputs("]}\n", stderr);
}
#endif
static int g_argc;
static char **g_argv;
static _Thread_local const char *g_file_json = G_FILE_JSON;

static void g_gc_init(void) {
    GC_set_all_interior_pointers(1);
    GC_INIT();
#ifdef GLYPH_GC_TIMING
    GC_set_on_collection_event(g_gc_event);
    atexit(g_gc_timing_report);
#endif
#ifdef GLYPH_ALLOC_STATS
    atexit(g_stats_report);
#endif
    const char *stress = getenv("GLYPH_GC_STRESS");
    g_gc_stress = stress && !strcmp(stress, "1");
}
static void g_fail(const char *code, const char *message, int line, int col) {
    #ifdef GLYPH_CONCURRENCY
    flockfile(stderr);
    #endif
    fputs("{\"file\":", stderr);
    fputs(g_file_json, stderr);
    fputc(',', stderr);
    fprintf(stderr, "\"code\":\"%s\",\"severity\":\"error\",\"message\":\"%s\",\"span\":{\"start\":{\"line\":%d,\"column\":%d},\"end\":{\"line\":%d,\"column\":%d}}}\n", code, message, line, col, line, col + 1);
    #ifdef GLYPH_CONCURRENCY
    funlockfile(stderr);
    #endif
    #ifdef GLYPH_CONCURRENCY
    /* Another thread may still own a service/stdio resource. Do not run
       main-thread atexit handlers concurrently with its active operation. */
    fflush(stderr);
    _Exit(70);
    #else
    exit(70);
    #endif
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
static g_array g_allocate_mode(int64_t n, size_t size, int l, int c, bool atomic, bool clear) {
    if (!size || n<0 || (uint64_t)n>SIZE_MAX/size) g_fail("R004","invalid allocation size",l,c);
    size_t bytes = (n ? (size_t)n : 1) * size;
    if (g_gc_stress) GC_gcollect();
    void *data = atomic ? GC_malloc_atomic(bytes) : GC_malloc(bytes);
    if (!data) g_fail("R004","allocation failed",l,c);
    /* Atomic allocations are not cleared by BDWGC. Preserve zero initialization. */
    if (atomic && clear) memset(data, 0, bytes);
    G_ALLOC_RECORD(0, bytes);
    return (g_array){data,n};
}
static g_array g_allocate(int64_t n, size_t size, int l, int c, bool atomic) {
    return g_allocate_mode(n, size, l, c, atomic, true);
}
/* Only fully overwritten, pointer-free storage may call this helper. */
static g_array g_new_atomic_uninit(int64_t n, size_t size, int l, int c) {
#ifdef GLYPH_ZERO_INIT
    return g_allocate(n, size, l, c, true);
#else
    return g_allocate_mode(n, size, l, c, true, false);
#endif
}
static g_array g_new(int64_t n, size_t size, int l, int c) {
    return g_allocate(n,size,l,c,false);
}
static g_array g_new_atomic(int64_t n, size_t size, int l, int c) {
    return g_allocate(n,size,l,c,true);
}
/* Explicit domains currently contain primitive elements only. */
#include <stddef.h>
typedef struct g_arena_chunk {
    struct g_arena_chunk *next;
    size_t used, capacity;
    max_align_t alignment;
    unsigned char data[];
} g_arena_chunk;
typedef struct { g_arena_chunk *head; } g_arena;
static size_t g_storage_bytes(int64_t n, size_t size, int l, int c) {
    if (!size || n < 0 || (uint64_t)n > SIZE_MAX / size)
        g_fail("R004", "invalid allocation size", l, c);
    return (n ? (size_t)n : 1) * size;
}
static g_array g_owned_new(int64_t n, size_t size, int l, int c) {
    size_t bytes = g_storage_bytes(n, size, l, c);
    void *p = malloc(bytes);
    if (!p) g_fail("R004", "allocation failed", l, c);
    G_ALLOC_RECORD(2, bytes);
    return (g_array){p, n};
}
static void g_owned_free(g_array *a) { free(a->data); a->data = NULL; a->len = 0; }
static g_array g_owned_move(g_array *a) { g_array b = *a; a->data = NULL; a->len = 0; return b; }
static g_array g_arena_new(g_arena *arena, int64_t n, size_t size, int l, int c) {
    size_t bytes = g_storage_bytes(n, size, l, c), align = _Alignof(max_align_t);
    if (bytes > SIZE_MAX - align - sizeof(g_arena_chunk)) g_fail("R004", "invalid allocation size", l, c);
    size_t padded = (bytes + align - 1) / align * align;
    g_arena_chunk *chunk = arena->head;
    if (!chunk || padded > chunk->capacity - chunk->used) {
        size_t capacity = padded > 65536 ? padded : 65536;
        chunk = malloc(sizeof(*chunk) + capacity);
        if (!chunk) g_fail("R004", "allocation failed", l, c);
        chunk->next = arena->head; chunk->used = 0; chunk->capacity = capacity;
        arena->head = chunk;
    }
    void *p = chunk->data + chunk->used;
    chunk->used += padded;
    G_ALLOC_RECORD(1, bytes);
    return (g_array){p, n};
}
static void g_arena_leave(g_arena *arena) {
    while (arena->head) { g_arena_chunk *p = arena->head; arena->head = p->next; free(p); }
}
static g_array g_reuse_atomic(g_array previous, int64_t n, size_t size, int l, int c) {
    (void)g_storage_bytes(n, size, l, c);
    return previous.len == n ? previous : g_new_atomic_uninit(n, size, l, c);
}
static void g_args_init(int argc, char **argv) {
    g_argc=argc; g_argv=argv;
#ifdef _WIN32
    /* The CRT's narrow argv uses the active Windows code page, not UTF-8. */
    int count=0;
    wchar_t **wide=CommandLineToArgvW(GetCommandLineW(),&count);
    if(!wide) g_fail("R009","cannot read command line",1,1);
    char **utf8=g_new((int64_t)count+1,sizeof(char*),1,1).data;
    for(int i=0;i<count;i++) {
        int n=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide[i],-1,NULL,0,NULL,NULL);
        if(!n) { LocalFree(wide); g_fail("R009","argument is not valid Unicode",1,1); }
        utf8[i]=g_new_atomic(n,1,1,1).data;
        if(!WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide[i],-1,utf8[i],n,NULL,NULL)) {
            LocalFree(wide); g_fail("R009","cannot encode argument",1,1);
        }
    }
    LocalFree(wide);
    g_argc=count; g_argv=utf8;
#endif
}
static int64_t g_index(g_array a, int64_t i, int l, int c) {
    if (i<0 || i>=a.len) g_fail("R003","array index out of bounds",l,c);
    return i;
}
static g_array g_clone(g_array a, size_t size, int l, int c) {
    g_array b=g_new(a.len,size,l,c); memcpy(b.data,a.data,(size_t)a.len*size); return b;
}
static g_array g_clone_atomic(g_array a, size_t size, int l, int c) {
    g_array b=g_new_atomic_uninit(a.len,size,l,c); memcpy(b.data,a.data,(size_t)a.len*size); return b;
}
static g_array g_range(int64_t n, int l, int c) {
    g_array a=g_new_atomic_uninit(n,sizeof(int64_t),l,c);
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
