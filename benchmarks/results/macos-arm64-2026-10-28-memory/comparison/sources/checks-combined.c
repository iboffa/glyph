#define G_FILE_JSON "\042\057\125\163\145\162\163\057\151\147\151\156\157\057\147\154\171\160\150\057\142\145\156\143\150\155\141\162\153\163\057\162\145\163\165\154\164\163\057\155\141\143\157\163\055\141\162\155\066\064\055\062\060\062\066\055\061\060\055\062\070\055\155\145\155\157\162\171\057\143\157\155\160\141\162\151\163\157\156\057\163\157\165\162\143\145\163\057\143\150\145\143\153\163\056\147\154\171\042"
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

#ifndef GLYPH_STD_RUNTIME_H
#define GLYPH_STD_RUNTIME_H
#include <sys/stat.h>
#ifndef _WIN32
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
extern char **environ;
#endif

/* Public value records. Error payloads use static strings and need no allocation. */
#define G_RESULT_TYPE(Name, Type, Empty) \
    typedef struct g_record_##Name { \
        bool m_ok; Type m_value; g_str m_code; g_str m_message; \
    } g_record_##Name; \
    static g_record_##Name g_error_##Name(const char *code, const char *message) { \
        return (g_record_##Name){false, Empty, \
            {code, (int64_t)strlen(code)}, {message, (int64_t)strlen(message)}}; \
    }
G_RESULT_TYPE(IntResult, int64_t, 0)
G_RESULT_TYPE(FloatResult, double, 0)
G_RESULT_TYPE(StringResult, g_str, ((g_str){"",0}))
G_RESULT_TYPE(BoolResult, bool, false)
G_RESULT_TYPE(BytesResult, g_array, ((g_array){NULL,0}))
G_RESULT_TYPE(StringsResult, g_array, ((g_array){NULL,0}))
#undef G_RESULT_TYPE
/* HTTP transport success includes non-2xx responses; payload and headers are bytes. */
typedef struct g_record_HttpResult {
    bool m_ok; g_array m_value; g_str m_code, m_message;
    int64_t m_status; g_array m_headers;
} g_record_HttpResult;
static g_record_HttpResult g_error_HttpResult(const char *message) {
    return (g_record_HttpResult){false,{NULL,0},{"R014",4},
        {message,(int64_t)strlen(message)},0,{NULL,0}};
}

/* Legacy APIs turn the same result into their established fatal diagnostic. */
static void g_result_require(bool ok, g_str code, g_str message, int l, int c) {
    if (!ok) g_fail(code.data, message.data, l, c);
}

static bool g_utf8(g_str s) {
    for (int64_t i=0; i<s.len;) {
        unsigned x=(unsigned char)s.data[i++], n=0, cp=0, minimum=0;
        if (x<128) continue;
        if (x>=194 && x<=223) { n=1; cp=x&31; minimum=128; }
        else if (x>=224 && x<=239) { n=2; cp=x&15; minimum=2048; }
        else if (x>=240 && x<=244) { n=3; cp=x&7; minimum=65536; }
        else return false;
        if (s.len-i<n) return false;
        while (n--) {
            x=(unsigned char)s.data[i++];
            if ((x&192)!=128) return false;
            cp=(cp<<6)|(x&63);
        }
        if (cp<minimum || cp>0x10ffff || (cp>=0xd800 && cp<=0xdfff)) return false;
    }
    return true;
}
static g_str g_text(const char *p, int64_t n, int l, int c) {
    g_array a=g_new_atomic(n,1,l,c);
    if (n) memcpy(a.data,p,(size_t)n);
    return (g_str){a.data,n};
}
static char *g_cstr(g_str s, int l, int c) {
    if (memchr(s.data,0,(size_t)s.len)) g_fail("R009","embedded NUL is not allowed here",l,c);
    g_array a=g_new_atomic(g_add(s.len,1,l,c),1,l,c);
    memcpy(a.data,s.data,(size_t)s.len);
    return a.data;
}
#ifdef _WIN32
static wchar_t *g_wstr(g_str s, int l, int c) {
    char *text=g_cstr(s,l,c);
    int n=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,-1,NULL,0);
    if(!n) g_fail("R009","text is not valid UTF-8",l,c);
    wchar_t *wide=g_new_atomic(n,sizeof(wchar_t),l,c).data;
    if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,text,-1,wide,n))
        g_fail("R009","cannot convert UTF-8",l,c);
    return wide;
}
#endif
static FILE *g_fopen(g_str path, const char *mode, int l, int c) {
#ifdef _WIN32
    wchar_t wide_mode[4]={0};
    for(int i=0;mode[i] && i<3;i++) wide_mode[i]=(wchar_t)mode[i];
    return _wfopen(g_wstr(path,l,c),wide_mode);
#else
    return fopen(g_cstr(path,l,c),mode);
#endif
}
static g_str g_std_join(g_array parts, int64_t count, g_str sep, int l, int c) {
    if (count<0 || count>parts.len) g_fail("R003","invalid join count",l,c);
    g_str *p=parts.data;
    int64_t n=0;
    for (int64_t i=0;i<count;i++) {
        n=g_add(n,p[i].len,l,c);
        if (i) n=g_add(n,sep.len,l,c);
    }
    char *out=g_new_atomic(n,1,l,c).data;
    int64_t pos=0;
    for (int64_t i=0;i<count;i++) {
        if(i && sep.len) { memcpy(out+pos,sep.data,(size_t)sep.len); pos+=sep.len; }
        if(p[i].len) { memcpy(out+pos,p[i].data,(size_t)p[i].len); pos+=p[i].len; }
    }
    return (g_str){out,n};
}
static g_str g_std_concat(g_str a, g_str b, int l, int c) {
    g_str parts[2]={a,b};
    return g_std_join((g_array){parts,2},2,(g_str){"",0},l,c);
}
static g_str g_std_slice(g_str s, int64_t start, int64_t end, int l, int c) {
    if (start<0 || end<start || end>s.len) g_fail("R003","string slice out of bounds",l,c);
    if ((start<s.len && ((unsigned char)s.data[start]&192)==128) ||
        (end<s.len && ((unsigned char)s.data[end]&192)==128))
        g_fail("R009","slice must use UTF-8 boundaries",l,c);
    return (g_str){s.data+start,end-start};
}
static int64_t g_std_byte_at(g_str s, int64_t i, int l, int c) {
    if (i<0 || i>=s.len) g_fail("R003","string byte index out of bounds",l,c);
    return (unsigned char)s.data[i];
}
static g_str g_std_chr(int64_t x, int l, int c) {
    if (x<0 || x>0x10ffff || (x>=0xd800 && x<=0xdfff))
        g_fail("R009","invalid Unicode scalar",l,c);
    char b[4]; int n;
    if(x<128) { b[0]=(char)x; n=1; }
    else if(x<2048) { b[0]=192|(x>>6); b[1]=128|(x&63); n=2; }
    else if(x<65536) { b[0]=224|(x>>12); b[1]=128|((x>>6)&63); b[2]=128|(x&63); n=3; }
    else { b[0]=240|(x>>18); b[1]=128|((x>>12)&63); b[2]=128|((x>>6)&63); b[3]=128|(x&63); n=4; }
    return g_text(b,n,l,c);
}
static g_str g_std_str_i64(int64_t n, int l, int c) {
    char b[32]; int count=snprintf(b,sizeof b,"%lld",(long long)n);
    return g_text(b,count,l,c);
}
static g_str g_std_str_f64(double n, int l, int c) {
    char b[64]; int count=snprintf(b,sizeof b,"%.17g",n);
    return g_text(b,count,l,c);
}
static g_record_IntResult g_std_try_parse_i64(g_str s, int l, int c) {
    if (memchr(s.data,0,(size_t)s.len))
        return g_error_IntResult("R009","embedded NUL is not allowed here");
    char *p=g_cstr(s,l,c), *end;
    if(!s.len || (*p!='-' && (*p<'0' || *p>'9')))
        return g_error_IntResult("R009","invalid integer text");
    errno=0; long long value=strtoll(p,&end,10);
    if(errno || end==p || *end || value<INT64_MIN || value>INT64_MAX)
        return g_error_IntResult("R009","invalid integer text");
    return (g_record_IntResult){true,value,{"",0},{"",0}};
}
static int64_t g_std_parse_i64(g_str s, int l, int c) {
    g_record_IntResult r=g_std_try_parse_i64(s,l,c);
    g_result_require(r.m_ok,r.m_code,r.m_message,l,c);
    return r.m_value;
}
static g_record_FloatResult g_std_try_parse_f64(g_str s, int l, int c) {
    if (memchr(s.data,0,(size_t)s.len))
        return g_error_FloatResult("R009","embedded NUL is not allowed here");
    char *p=g_cstr(s,l,c), *end;
    if(!s.len || (*p!='-' && *p!='+' && *p!='.' && (*p<'0' || *p>'9')))
        return g_error_FloatResult("R009","invalid floating text");
    errno=0; double value=strtod(p,&end);
    /* Underflow to a finite subnormal/zero is allowed, like source literals. */
    if(end==p || *end || !isfinite(value))
        return g_error_FloatResult("R009","invalid floating text");
    return (g_record_FloatResult){true,value,{"",0},{"",0}};
}
static double g_std_parse_f64(g_str s, int l, int c) {
    g_record_FloatResult r=g_std_try_parse_f64(s,l,c);
    g_result_require(r.m_ok,r.m_code,r.m_message,l,c);
    return r.m_value;
}
static bool g_std_valid_f64(g_str s, int l, int c) {
    return g_std_try_parse_f64(s,l,c).m_ok;
}
static g_record_StringResult g_std_try_read_file(g_str path, int l, int c) {
    if (memchr(path.data,0,(size_t)path.len))
        return g_error_StringResult("R009","embedded NUL is not allowed here");
    FILE *f=g_fopen(path,"rb",l,c);
    if(!f) return g_error_StringResult("R010","cannot open input file");
    if(fseek(f,0,SEEK_END)) { fclose(f); return g_error_StringResult("R010","cannot seek input file"); }
    long n=ftell(f);
    if(n<0 || fseek(f,0,SEEK_SET)) { fclose(f); return g_error_StringResult("R010","cannot size input file"); }
    char *data=g_new_atomic(n,1,l,c).data;
    size_t got=fread(data,1,(size_t)n,f);
    bool read_error=ferror(f)!=0;
    int close_error=fclose(f);
    if(got!=(size_t)n || read_error || close_error)
        return g_error_StringResult("R010","cannot read input file");
    g_str result={data,n};
    if(!g_utf8(result)) return g_error_StringResult("R009","file is not valid UTF-8");
    return (g_record_StringResult){true,result,{"",0},{"",0}};
}
static g_str g_std_read_file(g_str path, int l, int c) {
    g_record_StringResult r=g_std_try_read_file(path,l,c);
    g_result_require(r.m_ok,r.m_code,r.m_message,l,c);
    return r.m_value;
}
static g_record_BoolResult g_std_try_write_file(g_str path, g_str text, int l, int c) {
    if (memchr(path.data,0,(size_t)path.len))
        return g_error_BoolResult("R009","embedded NUL is not allowed here");
    FILE *f=g_fopen(path,"wb",l,c);
    if(!f) return g_error_BoolResult("R010","cannot open output file");
    size_t wrote=fwrite(text.data,1,(size_t)text.len,f);
    int close_error=fclose(f);
    if(wrote!=(size_t)text.len || close_error)
        return g_error_BoolResult("R010","cannot write output file");
    return (g_record_BoolResult){true,true,{"",0},{"",0}};
}
static void g_std_write_file(g_str path, g_str text, int l, int c) {
    g_record_BoolResult r=g_std_try_write_file(path,text,l,c);
    g_result_require(r.m_ok,r.m_code,r.m_message,l,c);
}
static bool g_std_same_file(g_str a, g_str b, int l, int c) {
    if(g_eq(a,b)) return true;
#ifdef _WIN32
    DWORD share=FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_SHARE_DELETE;
    HANDLE x=CreateFileW(g_wstr(a,l,c),0,share,NULL,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,NULL);
    if(x==INVALID_HANDLE_VALUE) return false;
    HANDLE y=CreateFileW(g_wstr(b,l,c),0,share,NULL,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,NULL);
    BY_HANDLE_FILE_INFORMATION xi,yi;
    bool same=y!=INVALID_HANDLE_VALUE && GetFileInformationByHandle(x,&xi) && GetFileInformationByHandle(y,&yi) &&
        xi.dwVolumeSerialNumber==yi.dwVolumeSerialNumber && xi.nFileIndexHigh==yi.nFileIndexHigh && xi.nFileIndexLow==yi.nFileIndexLow;
    CloseHandle(x);
    if(y!=INVALID_HANDLE_VALUE) CloseHandle(y);
    return same;
#else
    struct stat x,y;
    return !stat(g_cstr(a,l,c),&x) && !stat(g_cstr(b,l,c),&y) &&
        x.st_dev==y.st_dev && x.st_ino==y.st_ino;
#endif
}
static bool g_std_file_exists(g_str path, int l, int c) {
#ifdef _WIN32
    struct _stat64 info;
    return !_wstat64(g_wstr(path,l,c),&info) && (info.st_mode&_S_IFMT)==_S_IFREG;
#else
    struct stat info;
    return !stat(g_cstr(path,l,c), &info) && S_ISREG(info.st_mode);
#endif
}
static g_str g_std_arg(int64_t i, int l, int c) {
    if(i<0 || i>=g_argc-1) g_fail("R005","missing string argument",l,c);
    char *p=g_argv[i+1];
    g_str result={p,(int64_t)strlen(p)};
    if(!g_utf8(result)) g_fail("R009","argument is not valid UTF-8",l,c);
    return result;
}
static int64_t g_std_argc(int l, int c) { (void)l; (void)c; return g_argc-1; }
static g_str g_std_getenv(g_str name, int l, int c) {
    char *p=getenv(g_cstr(name,l,c));
    if(!p) return (g_str){"",0};
    g_str result={p,(int64_t)strlen(p)};
    if(!g_utf8(result)) g_fail("R009","environment value is not valid UTF-8",l,c);
    return result;
}
static g_str g_std_platform(int l, int c) {
    (void)l; (void)c;
#ifdef _WIN32
    return (g_str){"windows",7};
#elif defined(__APPLE__)
    return (g_str){"macos",5};
#else
    return (g_str){"posix",5};
#endif
}
static g_record_IntResult g_std_try_process(g_array args, int l, int c) {
    if(!args.len) return g_error_IntResult("R010","process requires an executable");
    for(int64_t i=0;i<args.len;i++) {
        g_str arg=((g_str*)args.data)[i];
        if(memchr(arg.data,0,(size_t)arg.len))
            return g_error_IntResult("R009","embedded NUL is not allowed here");
    }
    char **argv=g_new(g_add(args.len,1,l,c),sizeof(char*),l,c).data;
    for(int64_t i=0;i<args.len;i++) argv[i]=g_cstr(((g_str*)args.data)[i],l,c);
#ifdef _WIN32
    return g_error_IntResult("R010","process is currently supported on POSIX hosts only");
#else
    pid_t pid;
    fflush(stdout); fflush(stderr);
    int error=posix_spawnp(&pid,argv[0],NULL,NULL,argv,environ);
    if(error) return g_error_IntResult("R010","cannot launch executable");
    int status;
    while(waitpid(pid,&status,0)<0) {
        if(errno!=EINTR) return g_error_IntResult("R010","cannot wait for executable");
    }
    int64_t code=WIFEXITED(status) ? WEXITSTATUS(status) : 128+WTERMSIG(status);
    return (g_record_IntResult){true,code,{"",0},{"",0}};
#endif
}
static int64_t g_std_process(g_array args, int l, int c) {
    g_record_IntResult r=g_std_try_process(args,l,c);
    g_result_require(r.m_ok,r.m_code,r.m_message,l,c);
    return r.m_value;
}
static void g_std_eprint(g_str s, int l, int c) {
    (void)l; (void)c; fwrite(s.data,1,(size_t)s.len,stderr); fputc('\n',stderr);
}
static void g_std_exit(int64_t code, int l, int c) {
    (void)l; (void)c; exit((int)((uint64_t)code&255));
}
#endif

#ifndef GLYPH_IO_RUNTIME_H
#define GLYPH_IO_RUNTIME_H

/* Bytes use existing [int] storage. Validate the entire array before any write. */
static bool g_bytes_valid(g_array bytes) {
    const int64_t *p=bytes.data;
    for(int64_t i=0;i<bytes.len;i++) if(p[i]<0 || p[i]>255) return false;
    return true;
}
static g_array g_std_encode_utf8(g_str text, int l, int c) {
    g_array out=g_new_atomic(text.len,sizeof(int64_t),l,c);
    for(int64_t i=0;i<text.len;i++) ((int64_t*)out.data)[i]=(unsigned char)text.data[i];
    return out;
}
static g_record_StringResult g_std_try_decode_utf8(g_array bytes, int l, int c) {
    if(!g_bytes_valid(bytes)) return g_error_StringResult("R009","byte outside 0..255");
    char *data=g_new_atomic(bytes.len,1,l,c).data;
    for(int64_t i=0;i<bytes.len;i++) data[i]=(char)((int64_t*)bytes.data)[i];
    g_str text={data,bytes.len};
    if(!g_utf8(text)) return g_error_StringResult("R009","bytes are not valid UTF-8");
    return (g_record_StringResult){true,text,{"",0},{"",0}};
}

/* IDs are never reused: a stale or copied closed handle cannot alias a new file.
 * Only live handles are rooted; close removes its entry. GC does not close files. */
typedef struct g_file_entry {
    int64_t id;
    FILE *file;
    bool readable;
    struct g_file_entry *next;
} g_file_entry;
static g_file_entry *g_files;
static int64_t g_file_serial;
static g_file_entry *g_file_find(int64_t id) {
    for(g_file_entry *e=g_files;e;e=e->next) if(e->id==id) return e;
    return NULL;
}
static g_record_IntResult g_std_try_open(g_str path, g_str mode, int l, int c) {
    if(memchr(path.data,0,(size_t)path.len))
        return g_error_IntResult("R009","embedded NUL is not allowed here");
    if(mode.len!=1 || (mode.data[0]!='r' && mode.data[0]!='w' && mode.data[0]!='a'))
        return g_error_IntResult("R010","file mode must be r, w or a");
    if(g_file_serial==INT64_MAX) return g_error_IntResult("R010","file handle IDs exhausted");
    /* Allocate before acquiring a file, including before truncation. */
    g_file_entry *e=g_new(1,sizeof(*e),l,c).data;
    char m[3]={mode.data[0],'b',0};
    FILE *f=g_fopen(path,m,l,c);
    if(!f) return g_error_IntResult("R010","cannot open file");
    e->id=++g_file_serial; e->file=f; e->readable=m[0]=='r';
    e->next=g_files; g_files=e;
    return (g_record_IntResult){true,e->id,{"",0},{"",0}};
}
static g_record_BytesResult g_std_try_read(int64_t id, int64_t count, int l, int c) {
    g_file_entry *e=g_file_find(id);
    if(!e || !e->readable) return g_error_BytesResult("R010","invalid or non-readable file handle");
    if(count<=0) return g_error_BytesResult("R010","read count must be positive");
    /* Read with a fixed scratch buffer; only the returned array scales with count. */
    g_array out=g_new_atomic(count,sizeof(int64_t),l,c);
    int64_t used=0;
    unsigned char buffer[8192];
    while(used<count) {
        size_t want=(size_t)((count-used)>8192 ? 8192 : count-used);
        size_t n=fread(buffer,1,want,e->file);
        for(size_t i=0;i<n;i++) ((int64_t*)out.data)[used++]=buffer[i];
        if(ferror(e->file)) return g_error_BytesResult("R010","cannot read file");
        if(n<want) break;
    }
    out.len=used;
    return (g_record_BytesResult){true,out,{"",0},{"",0}};
}
static g_record_IntResult g_std_try_write(int64_t id, g_array bytes, int l, int c) {
    (void)l; (void)c;
    g_file_entry *e=g_file_find(id);
    if(!e || e->readable) return g_error_IntResult("R010","invalid or non-writable file handle");
    if(!g_bytes_valid(bytes)) return g_error_IntResult("R009","byte outside 0..255");
    unsigned char buffer[8192];
    int64_t used=0;
    while(used<bytes.len) {
        size_t n=(size_t)((bytes.len-used)>8192 ? 8192 : bytes.len-used);
        for(size_t i=0;i<n;i++) buffer[i]=(unsigned char)((int64_t*)bytes.data)[used+(int64_t)i];
        if(fwrite(buffer,1,n,e->file)!=n) return g_error_IntResult("R010","cannot write file");
        used+=(int64_t)n;
    }
    return (g_record_IntResult){true,used,{"",0},{"",0}};
}
static g_record_BoolResult g_std_try_flush(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_file_entry *e=g_file_find(id);
    if(!e || e->readable) return g_error_BoolResult("R010","invalid or non-writable file handle");
    if(fflush(e->file)) return g_error_BoolResult("R010","cannot flush file");
    return (g_record_BoolResult){true,true,{"",0},{"",0}};
}
static g_record_BoolResult g_std_try_close(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_file_entry **link=&g_files;
    while(*link && (*link)->id!=id) link=&(*link)->next;
    if(!*link) return g_error_BoolResult("R010","invalid or closed file handle");
    g_file_entry *e=*link;
    *link=e->next;
    FILE *f=e->file;
    e->file=NULL; e->next=NULL;
    if(fclose(f)) return g_error_BoolResult("R010","cannot close file");
    return (g_record_BoolResult){true,true,{"",0},{"",0}};
}
static g_record_BytesResult g_std_try_read_bytes(g_str path, int l, int c) {
    g_record_IntResult opened=g_std_try_open(path,(g_str){"r",1},l,c);
    if(!opened.m_ok) return (g_record_BytesResult){false,{NULL,0},opened.m_code,opened.m_message};
    int64_t used=0, capacity=8192;
    g_array out=g_new_atomic(capacity,sizeof(int64_t),l,c);
    for(;;) {
        g_record_BytesResult part=g_std_try_read(opened.m_value,8192,l,c);
        if(!part.m_ok) {
            g_std_try_close(opened.m_value,l,c);
            return part;
        }
        int64_t needed=g_add(used,part.m_value.len,l,c);
        if(needed>capacity) {
            capacity=g_add(capacity,capacity,l,c);
            g_array next=g_new_atomic(capacity,sizeof(int64_t),l,c);
            memcpy(next.data,out.data,(size_t)used*sizeof(int64_t));
            out=next;
        }
        memcpy((int64_t*)out.data+used,part.m_value.data,(size_t)part.m_value.len*sizeof(int64_t));
        used=needed;
        if(part.m_value.len<8192) break;
    }
    g_record_BoolResult closed=g_std_try_close(opened.m_value,l,c);
    if(!closed.m_ok) return (g_record_BytesResult){false,{NULL,0},closed.m_code,closed.m_message};
    out.len=used;
    return (g_record_BytesResult){true,out,{"",0},{"",0}};
}
static g_record_BoolResult g_std_try_write_bytes(g_str path, g_array bytes, int l, int c) {
    if(!g_bytes_valid(bytes)) return g_error_BoolResult("R009","byte outside 0..255");
    g_record_IntResult opened=g_std_try_open(path,(g_str){"w",1},l,c);
    if(!opened.m_ok) return (g_record_BoolResult){false,false,opened.m_code,opened.m_message};
    g_record_IntResult wrote=g_std_try_write(opened.m_value,bytes,l,c);
    g_record_BoolResult closed=g_std_try_close(opened.m_value,l,c);
    if(!wrote.m_ok) return (g_record_BoolResult){false,false,wrote.m_code,wrote.m_message};
    return closed;
}
#endif

#ifndef GLYPH_JSON_RUNTIME_H
#define GLYPH_JSON_RUNTIME_H

/* JSON values are validated UTF-8 text fragments, preserving number lexemes.
 * Each operation parses once into a temporary GC-owned tree. No global roots. */
typedef enum { G_JSON_NULL, G_JSON_BOOL, G_JSON_NUMBER, G_JSON_STRING,
               G_JSON_ARRAY, G_JSON_OBJECT } g_json_kind;
typedef struct g_json_node {
    g_json_kind kind;
    g_str raw, text, key;
    int64_t count;
    struct g_json_node *child, *next;
} g_json_node;
typedef struct { g_str source; int64_t pos; const char *error; int l,c; } g_json_parser;
static bool g_json_error(g_json_parser *p, const char *error) {
    if(!p->error) p->error=error;
    return false;
}
static int g_json_peek(g_json_parser *p) {
    return p->pos<p->source.len ? (unsigned char)p->source.data[p->pos] : -1;
}
static void g_json_space(g_json_parser *p) {
    int b;
    while((b=g_json_peek(p))==32 || b==9 || b==10 || b==13) p->pos++;
}
static bool g_json_take(g_json_parser *p, int b) {
    if(g_json_peek(p)!=b) return false;
    p->pos++; return true;
}
static bool g_json_hex4(g_json_parser *p, unsigned *value) {
    *value=0;
    for(int i=0;i<4;i++) {
        int b=g_json_peek(p), digit;
        if(b>='0' && b<='9') digit=b-'0';
        else if(b>='a' && b<='f') digit=b-'a'+10;
        else if(b>='A' && b<='F') digit=b-'A'+10;
        else return g_json_error(p,"invalid JSON Unicode escape");
        p->pos++; *value=(*value<<4)|(unsigned)digit;
    }
    return true;
}
static bool g_json_read_string(g_json_parser *p, g_str *text) {
    if(!g_json_take(p,'"')) return g_json_error(p,"expected JSON string");
    int64_t start=p->pos, end=start;
    /* Locate the closing quote first so allocation is proportional to this string. */
    while(end<p->source.len && p->source.data[end]!='"') {
        if(p->source.data[end]=='\\') end++;
        if(end<p->source.len) end++;
    }
    if(end==p->source.len) return g_json_error(p,"unterminated JSON string");
    char *out=g_new_atomic(end-start,1,p->l,p->c).data;
    int64_t n=0;
    while(p->pos<end) {
        int b=(unsigned char)p->source.data[p->pos++];
        if(b<32) return g_json_error(p,"unescaped control in JSON string");
        if(b!='\\') { out[n++]=(char)b; continue; }
        b=g_json_peek(p); p->pos++;
        switch(b) {
            case '"': case '\\': case '/': out[n++]=(char)b; break;
            case 'b': out[n++]='\b'; break;
            case 'f': out[n++]='\f'; break;
            case 'n': out[n++]='\n'; break;
            case 'r': out[n++]='\r'; break;
            case 't': out[n++]='\t'; break;
            case 'u': {
                unsigned cp,lo;
                if(!g_json_hex4(p,&cp)) return false;
                if(cp>=0xd800 && cp<=0xdbff) {
                    if(!g_json_take(p,'\\') || !g_json_take(p,'u') || !g_json_hex4(p,&lo))
                        return g_json_error(p,"missing JSON low surrogate");
                    if(lo<0xdc00 || lo>0xdfff) return g_json_error(p,"invalid JSON low surrogate");
                    cp=0x10000+((cp-0xd800)<<10)+(lo-0xdc00);
                } else if(cp>=0xdc00 && cp<=0xdfff) return g_json_error(p,"unpaired JSON surrogate");
                if(cp<128) out[n++]=(char)cp;
                else if(cp<2048) { out[n++]=(char)(192|(cp>>6)); out[n++]=(char)(128|(cp&63)); }
                else if(cp<65536) { out[n++]=(char)(224|(cp>>12)); out[n++]=(char)(128|((cp>>6)&63)); out[n++]=(char)(128|(cp&63)); }
                else { out[n++]=(char)(240|(cp>>18)); out[n++]=(char)(128|((cp>>12)&63)); out[n++]=(char)(128|((cp>>6)&63)); out[n++]=(char)(128|(cp&63)); }
                break;
            }
            default: return g_json_error(p,"invalid JSON string escape");
        }
    }
    if(!g_json_take(p,'"')) return g_json_error(p,"unterminated JSON string");
    *text=(g_str){out,n}; return true;
}
static bool g_json_digit(int b) { return b>='0' && b<='9'; }
static bool g_json_number(g_json_parser *p) {
    g_json_take(p,'-');
    if(!g_json_take(p,'0')) {
        if(g_json_peek(p)<'1' || g_json_peek(p)>'9') return g_json_error(p,"invalid JSON number");
        while(g_json_digit(g_json_peek(p))) p->pos++;
    }
    if(g_json_take(p,'.')) {
        if(!g_json_digit(g_json_peek(p))) return g_json_error(p,"invalid JSON fraction");
        while(g_json_digit(g_json_peek(p))) p->pos++;
    }
    if(g_json_take(p,'e') || g_json_take(p,'E')) {
        if(!g_json_take(p,'+')) g_json_take(p,'-');
        if(!g_json_digit(g_json_peek(p))) return g_json_error(p,"invalid JSON exponent");
        while(g_json_digit(g_json_peek(p))) p->pos++;
    }
    return true;
}
static g_json_node *g_json_value(g_json_parser *p, int depth) {
    g_json_space(p);
    int64_t start=p->pos;
    int b=g_json_peek(p);
    if(b<0) { g_json_error(p,"expected JSON value"); return NULL; }
    g_json_node *node=g_new(1,sizeof(*node),p->l,p->c).data;
    if(b=='[' || b=='{') {
        if(depth>=128) { g_json_error(p,"JSON nesting exceeds 128 containers"); return NULL; }
        bool object=b=='{';
        node->kind=object ? G_JSON_OBJECT : G_JSON_ARRAY;
        p->pos++;
        g_json_space(p);
        int close=object ? '}' : ']';
        g_json_node **tail=&node->child;
        if(!g_json_take(p,close)) for(;;) {
            g_str key={"",0};
            if(object) {
                if(!g_json_read_string(p,&key)) return NULL;
                g_json_space(p);
                if(!g_json_take(p,':')) { g_json_error(p,"expected JSON colon"); return NULL; }
            }
            g_json_node *child=g_json_value(p,depth+1);
            if(!child) return NULL;
            child->key=key;
            *tail=child; tail=&child->next; node->count++;
            g_json_space(p);
            if(g_json_take(p,close)) break;
            if(!g_json_take(p,',')) { g_json_error(p,"expected JSON comma or closing delimiter"); return NULL; }
            g_json_space(p);
        }
    } else if(b=='"') {
        node->kind=G_JSON_STRING;
        if(!g_json_read_string(p,&node->text)) return NULL;
    } else if(b=='-' || g_json_digit(b)) {
        node->kind=G_JSON_NUMBER;
        if(!g_json_number(p)) return NULL;
    } else {
        const char *literal=b=='t' ? "true" : b=='f' ? "false" : b=='n' ? "null" : "";
        size_t size=strlen(literal);
        if(!size || p->source.len-p->pos<(int64_t)size || memcmp(p->source.data+p->pos,literal,size)) {
            g_json_error(p,"invalid JSON value"); return NULL;
        }
        node->kind=b=='n' ? G_JSON_NULL : G_JSON_BOOL;
        p->pos+=(int64_t)size;
    }
    node->raw=(g_str){p->source.data+start,p->pos-start};
    return node;
}
static g_json_node *g_json_parse(g_str source, const char **error, int l, int c) {
    g_json_parser p={source,0,NULL,l,c};
    if(!g_utf8(source)) { *error="JSON input is not valid UTF-8"; return NULL; }
    g_json_node *root=g_json_value(&p,0);
    g_json_space(&p);
    if(root && p.pos!=source.len) { g_json_error(&p,"trailing content after JSON value"); root=NULL; }
    *error=p.error;
    return root;
}
static g_record_StringResult g_json_success(g_str value) {
    return (g_record_StringResult){true,value,{"",0},{"",0}};
}
static g_record_StringResult g_std_try_json_parse(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    return root ? g_json_success(root->raw) : g_error_StringResult("R012",error);
}
static g_record_StringResult g_std_try_json_kind(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R012",error);
    const char *names[]={"null","bool","number","string","array","object"};
    const char *name=names[root->kind];
    return g_json_success((g_str){name,(int64_t)strlen(name)});
}
static g_record_StringResult g_std_try_json_string(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R012",error);
    if(root->kind!=G_JSON_STRING) return g_error_StringResult("R012","expected JSON string");
    return g_json_success(root->text);
}
static g_record_StringResult g_std_try_json_get(g_str source, g_str key, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R012",error);
    if(root->kind!=G_JSON_OBJECT) return g_error_StringResult("R012","expected JSON object");
    g_json_node *found=NULL;
    for(g_json_node *n=root->child;n;n=n->next) if(g_eq(n->key,key)) found=n;
    return found ? g_json_success(found->raw) : g_error_StringResult("R012","JSON key not found");
}
static g_record_StringResult g_std_try_json_at(g_str source, int64_t index, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R012",error);
    if(root->kind!=G_JSON_ARRAY) return g_error_StringResult("R012","expected JSON array");
    if(index<0 || index>=root->count) return g_error_StringResult("R012","JSON index out of bounds");
    g_json_node *n=root->child;
    while(index--) n=n->next;
    return g_json_success(n->raw);
}
static g_record_IntResult g_std_try_json_len(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_IntResult("R012",error);
    if(root->kind!=G_JSON_ARRAY && root->kind!=G_JSON_OBJECT) return g_error_IntResult("R012","expected JSON array or object");
    return (g_record_IntResult){true,root->count,{"",0},{"",0}};
}
static g_record_StringsResult g_std_try_json_keys(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringsResult("R012",error);
    if(root->kind!=G_JSON_OBJECT) return g_error_StringsResult("R012","expected JSON object");
    g_array keys=g_new(root->count,sizeof(g_str),l,c);
    int64_t i=0;
    for(g_json_node *n=root->child;n;n=n->next) ((g_str*)keys.data)[i++]=n->key;
    return (g_record_StringsResult){true,keys,{"",0},{"",0}};
}
static g_str g_std_json_quote(g_str text, int l, int c) {
    int64_t size=2;
    for(int64_t i=0;i<text.len;i++) {
        unsigned char b=(unsigned char)text.data[i];
        size=g_add(size,b<32 ? 6 : b=='"' || b=='\\' ? 2 : 1,l,c);
    }
    char *out=g_new_atomic(size,1,l,c).data;
    const char *hex="0123456789abcdef";
    int64_t n=0; out[n++]='"';
    for(int64_t i=0;i<text.len;i++) {
        unsigned char b=(unsigned char)text.data[i];
        if(b<32) { out[n++]='\\'; out[n++]='u'; out[n++]='0'; out[n++]='0'; out[n++]=hex[b>>4]; out[n++]=hex[b&15]; }
        else { if(b=='"' || b=='\\') out[n++]='\\'; out[n++]=(char)b; }
    }
    out[n++]='"';
    return (g_str){out,n};
}
static g_record_StringResult g_json_build(g_array keys, g_array values, bool object, int l, int c) {
    if(object && keys.len!=values.len) return g_error_StringResult("R012","JSON keys and values have different lengths");
    g_array parts=g_new(g_add(g_mul(values.len,4,l,c),2,l,c),sizeof(g_str),l,c);
    g_str *p=parts.data;
    int64_t count=0;
    p[count++]=(g_str){object ? "{" : "[",1};
    for(int64_t i=0;i<values.len;i++) {
        g_record_StringResult value=g_std_try_json_parse(((g_str*)values.data)[i],l,c);
        if(!value.m_ok) return value;
        if(i) p[count++]=(g_str){",",1};
        if(object) {
            p[count++]=g_std_json_quote(((g_str*)keys.data)[i],l,c);
            p[count++]=(g_str){":",1};
        }
        p[count++]=value.m_value;
    }
    p[count++]=(g_str){object ? "}" : "]",1};
    g_str text=g_std_join(parts,count,(g_str){"",0},l,c);
    /* The new outer container must also fit the nesting bound. */
    return g_std_try_json_parse(text,l,c);
}
static g_record_StringResult g_std_try_json_array(g_array values, int l, int c) {
    return g_json_build((g_array){NULL,0},values,false,l,c);
}
static g_record_StringResult g_std_try_json_object(g_array keys, g_array values, int l, int c) {
    return g_json_build(keys,values,true,l,c);
}
#endif

#ifndef GLYPH_SERIALIZATION_RUNTIME_H
#define GLYPH_SERIALIZATION_RUNTIME_H
static g_record_StringResult g_std_try_base64_encode(g_array bytes, int l, int c) {
    if(!g_bytes_valid(bytes)) return g_error_StringResult("R009","byte outside 0..255");
    const char *alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    int64_t size=g_mul(g_add(bytes.len,2,l,c)/3,4,l,c);
    char *out=g_new_atomic(size,1,l,c).data;
    int64_t *p=bytes.data, n=0;
    for(int64_t i=0;i<bytes.len;i+=3) {
        unsigned v=(unsigned)p[i]<<16;
        if(i+1<bytes.len) v|=(unsigned)p[i+1]<<8;
        if(i+2<bytes.len) v|=(unsigned)p[i+2];
        out[n++]=alphabet[v>>18]; out[n++]=alphabet[(v>>12)&63];
        out[n++]=i+1<bytes.len ? alphabet[(v>>6)&63] : '=';
        out[n++]=i+2<bytes.len ? alphabet[v&63] : '=';
    }
    return (g_record_StringResult){true,{out,n},{"",0},{"",0}};
}
static int g_base64_digit(int b) {
    if(b>='A' && b<='Z') return b-'A';
    if(b>='a' && b<='z') return b-'a'+26;
    if(b>='0' && b<='9') return b-'0'+52;
    return b=='+' ? 62 : b=='/' ? 63 : -1;
}
static g_record_BytesResult g_std_try_base64_decode(g_str s, int l, int c) {
    if(s.len%4) return g_error_BytesResult("R016","invalid Base64 length");
    g_array out=g_new_atomic(s.len/4*3,sizeof(int64_t),l,c);
    int64_t n=0;
    for(int64_t i=0;i<s.len;i+=4) {
        int a=g_base64_digit(s.data[i]), b=g_base64_digit(s.data[i+1]);
        int d=g_base64_digit(s.data[i+2]), e=g_base64_digit(s.data[i+3]);
        bool pad2=s.data[i+2]=='=', pad1=s.data[i+3]=='=';
        if(a<0 || b<0 || (!pad2 && d<0) || (!pad1 && e<0) ||
           (pad2 && !pad1) || ((pad1 || pad2) && i+4!=s.len) ||
           (pad2 && (b&15)) || (pad1 && !pad2 && (d&3)))
            return g_error_BytesResult("R016","invalid Base64 alphabet or padding");
        int64_t *p=out.data;
        p[n++]=(a<<2)|(b>>4);
        if(!pad2) p[n++]=((b&15)<<4)|(d>>2);
        if(!pad1) p[n++]=((d&3)<<6)|e;
    }
    out.len=n;
    return (g_record_BytesResult){true,out,{"",0},{"",0}};
}
static void g_csv_push(g_array *out, int64_t *used, g_str value, int l, int c) {
    if(*used==out->len) {
        g_array next=g_new(g_mul(out->len,2,l,c),sizeof(g_str),l,c);
        memcpy(next.data,out->data,(size_t)*used*sizeof(g_str)); *out=next;
    }
    ((g_str*)out->data)[(*used)++]=value;
}
static g_record_StringsResult g_csv_scan(g_str text, bool fields, int l, int c) {
    g_array out=g_new(8,sizeof(g_str),l,c);
    char *decoded=fields ? g_new_atomic(g_add(text.len,1,l,c),1,l,c).data : NULL;
    int64_t i=0, used=0, decoded_n=0, rows=0;
    if(!text.len && !fields) return (g_record_StringsResult){true,{out.data,0},{"",0},{"",0}};
    do {
        int64_t row_start=i;
        for(;;) {
            int64_t start=decoded_n;
            if(i<text.len && text.data[i]=='"') {
                i++; bool closed=false;
                while(i<text.len) {
                    char b=text.data[i++];
                    if(b=='"') {
                        if(i<text.len && text.data[i]=='"') i++;
                        else { closed=true; break; }
                    }
                    if(fields) decoded[decoded_n++]=b;
                }
                if(!closed) return g_error_StringsResult("R016","unterminated CSV quoted field");
            } else {
                while(i<text.len && text.data[i]!=',' && text.data[i]!='\r' && text.data[i]!='\n') {
                    char b=text.data[i++];
                    if(b=='"') return g_error_StringsResult("R016","quote inside unquoted CSV field");
                    if(fields) decoded[decoded_n++]=b;
                }
            }
            if(fields) g_csv_push(&out,&used,(g_str){decoded+start,decoded_n-start},l,c);
            if(i<text.len && text.data[i]==',') { i++; continue; }
            break;
        }
        rows++;
        if(!fields) g_csv_push(&out,&used,(g_str){text.data+row_start,i-row_start},l,c);
        if(i<text.len) {
            if(text.data[i]=='\r') {
                i++;
                if(i==text.len || text.data[i]!='\n') return g_error_StringsResult("R016","CSV bare carriage return");
            }
            if(text.data[i]!='\n') return g_error_StringsResult("R016","unexpected text after CSV quote");
            i++;
        }
        if(fields && i<text.len) return g_error_StringsResult("R016","expected one CSV row");
    } while(i<text.len);
    (void)rows; out.len=used;
    return (g_record_StringsResult){true,out,{"",0},{"",0}};
}
static g_record_StringsResult g_std_try_csv_parse(g_str text, int l, int c) { return g_csv_scan(text,false,l,c); }
static g_record_StringsResult g_std_try_csv_row(g_str text, int l, int c) { return g_csv_scan(text,true,l,c); }
static g_str g_std_csv_row(g_array fields, int l, int c) {
    int64_t size=0;
    for(int64_t i=0;i<fields.len;i++) {
        g_str s=((g_str*)fields.data)[i];
        size=g_add(size,g_add(s.len,i ? 3 : 2,l,c),l,c);
        for(int64_t j=0;j<s.len;j++) if(s.data[j]=='"') size=g_add(size,1,l,c);
    }
    char *out=g_new_atomic(size,1,l,c).data; int64_t n=0;
    for(int64_t i=0;i<fields.len;i++) {
        if(i) out[n++]=',';
        out[n++]='"';
        g_str s=((g_str*)fields.data)[i];
        for(int64_t j=0;j<s.len;j++) { if(s.data[j]=='"') out[n++]='"'; out[n++]=s.data[j]; }
        out[n++]='"';
    }
    return (g_str){out,n};
}
static g_record_StringResult g_std_try_csv_write(g_array rows, int l, int c) {
    g_array parts=g_new(g_mul(rows.len,2,l,c),sizeof(g_str),l,c);
    for(int64_t i=0;i<rows.len;i++) {
        g_str row=((g_str*)rows.data)[i];
        g_record_StringsResult parsed=g_std_try_csv_row(row,l,c);
        if(!parsed.m_ok) return (g_record_StringResult){false,{"",0},parsed.m_code,parsed.m_message};
        ((g_str*)parts.data)[2*i]=g_std_csv_row(parsed.m_value,l,c);
        ((g_str*)parts.data)[2*i+1]=(g_str){"\r\n",2};
    }
    return (g_record_StringResult){true,g_std_join(parts,parts.len,(g_str){"",0},l,c),{"",0},{"",0}};
}
#endif

#ifndef GLYPH_COLLECTIONS_RUNTIME_H
#define GLYPH_COLLECTIONS_RUNTIME_H
/* Shared, GC-owned headers. No backing-storage pointers escape to Glyph. */
typedef struct {
    int kind, key_kind; /* list=0, map=1, set=2; key: int=0, bool=1, str=2 */
    int64_t len, cap, used;
    size_t key_size, value_size;
    bool key_atomic, value_atomic;
    void *keys, *values;
    unsigned char *states; /* empty=0, occupied=1, deleted=2 */
} g_collection;

static void *g_coll_bytes(int64_t n, size_t size, bool atomic, int l, int c) {
    return g_allocate(n, size, l, c, atomic).data;
}
static uint64_t g_coll_hash(g_collection *a, const void *key) {
    if (a->key_kind == 2) {
        g_str s = *(const g_str *)key;
        uint64_t h = UINT64_C(14695981039346656037);
        for (int64_t i = 0; i < s.len; ++i) h = (h ^ (unsigned char)s.data[i]) * UINT64_C(1099511628211);
        return h;
    }
    uint64_t x = a->key_kind == 1 ? *(const bool *)key : (uint64_t)*(const int64_t *)key;
    x ^= x >> 30; x *= UINT64_C(0xbf58476d1ce4e5b9);
    x ^= x >> 27; x *= UINT64_C(0x94d049bb133111eb);
    return x ^ (x >> 31);
}
static bool g_coll_equal(g_collection *a, const void *x, const void *y) {
    if (a->key_kind == 2) return g_eq(*(const g_str *)x, *(const g_str *)y);
    if (a->key_kind == 1) return *(const bool *)x == *(const bool *)y;
    return *(const int64_t *)x == *(const int64_t *)y;
}
static void *g_coll_key(g_collection *a, int64_t i) { return (char *)a->keys + (size_t)i * a->key_size; }
static void *g_coll_value(g_collection *a, int64_t i) { return (char *)a->values + (size_t)i * a->value_size; }
static int64_t g_coll_slot(g_collection *a, const void *key, bool *found) {
    int64_t i = (int64_t)(g_coll_hash(a, key) & (uint64_t)(a->cap - 1)), deleted = -1;
    while (a->states[i]) {
        if (a->states[i] == 1 && g_coll_equal(a, key, g_coll_key(a, i))) { *found = true; return i; }
        if (a->states[i] == 2 && deleted < 0) deleted = i;
        i = (i + 1) & (a->cap - 1);
    }
    *found = false;
    return deleted >= 0 ? deleted : i;
}
static void g_coll_resize(g_collection *a, int64_t cap, int l, int c) {
    if (a->kind == 0) {
        void *values = g_coll_bytes(cap, a->value_size, a->value_atomic, l, c);
        if (a->len) memcpy(values, a->values, (size_t)a->len * a->value_size);
        a->values = values; a->cap = cap;
        return;
    }
    g_collection old = *a;
    a->keys = g_coll_bytes(cap, a->key_size, a->key_atomic, l, c);
    if (a->kind == 1) a->values = g_coll_bytes(cap, a->value_size, a->value_atomic, l, c);
    a->states = g_coll_bytes(cap, 1, true, l, c);
    a->cap = cap; a->used = a->len;
    for (int64_t i = 0; i < old.cap; ++i) if (old.states[i] == 1) {
        bool found;
        int64_t j = g_coll_slot(a, g_coll_key(&old, i), &found);
        a->states[j] = 1;
        memcpy(g_coll_key(a, j), g_coll_key(&old, i), a->key_size);
        if (a->kind == 1) memcpy(g_coll_value(a, j), g_coll_value(&old, i), a->value_size);
    }
}
static bool g_coll_put(g_collection *a, const void *key, const void *value, int l, int c) {
    bool found;
    int64_t i = g_coll_slot(a, key, &found);
    if (!found) {
        /* Keep an empty slot; rebuild tombstones without unnecessary growth. */
        if (a->used >= a->cap - a->cap / 4) {
            int64_t cap = a->len < a->cap / 2 ? a->cap : g_mul(a->cap, 2, l, c);
            g_coll_resize(a, cap, l, c);
            i = g_coll_slot(a, key, &found);
        }
        if (!a->states[i]) ++a->used;
        a->states[i] = 1; ++a->len;
        memcpy(g_coll_key(a, i), key, a->key_size);
    }
    if (a->kind == 1) memcpy(g_coll_value(a, i), value, a->value_size);
    return !found;
}
static g_collection *g_coll_new(int kind, int key_kind, size_t key_size, size_t value_size,
                                bool key_atomic, bool value_atomic, g_array keys, g_array values, int l, int c) {
    if (kind == 1 && keys.len != values.len) g_fail("R007", "map key/value arrays must have equal lengths", l, c);
    g_collection *a = g_coll_bytes(1, sizeof(*a), false, l, c);
    a->kind = kind; a->key_kind = key_kind; a->key_size = key_size; a->value_size = value_size;
    a->key_atomic = key_atomic; a->value_atomic = value_atomic;
    g_coll_resize(a, kind == 0 && values.len > 8 ? values.len : 8, l, c);
    if (kind == 0) {
        a->len = values.len;
        if (values.len) memcpy(a->values, values.data, (size_t)values.len * value_size);
    } else {
        for (int64_t i = 0; i < keys.len; ++i)
            g_coll_put(a, (char *)keys.data + (size_t)i * key_size,
                       kind == 1 ? (char *)values.data + (size_t)i * value_size : NULL, l, c);
    }
    return a;
}
static int64_t g_coll_index(g_collection *a, int64_t i, int l, int c) {
    if (i < 0 || i >= a->len) g_fail("R003", "list index out of bounds", l, c);
    return i;
}
static void *g_coll_get(g_collection *a, const void *key, const void *fallback, int l, int c) {
    if (a->kind == 0) return g_coll_value(a, g_coll_index(a, *(const int64_t *)key, l, c));
    bool found;
    int64_t i = g_coll_slot(a, key, &found);
    if (found) return g_coll_value(a, i);
    if (fallback) return (void *)fallback;
    g_fail("R011", "map key not found", l, c);
    return NULL;
}
static bool g_coll_contains(g_collection *a, const void *key) {
    bool found; g_coll_slot(a, key, &found); return found;
}
static void g_coll_append(g_collection *a, const void *value, int l, int c) {
    if (a->len == a->cap) g_coll_resize(a, g_mul(a->cap, 2, l, c), l, c);
    memcpy(g_coll_value(a, a->len++), value, a->value_size);
}
static void g_coll_set(g_collection *a, int64_t i, const void *value, int l, int c) {
    memcpy(g_coll_value(a, g_coll_index(a, i, l, c)), value, a->value_size);
}
static void *g_coll_take(g_collection *a, int64_t i, int l, int c) {
    g_coll_index(a, i, l, c);
    void *value = g_coll_bytes(1, a->value_size, a->value_atomic, l, c);
    memcpy(value, g_coll_value(a, i), a->value_size);
    --a->len;
    memmove(g_coll_value(a, i), g_coll_value(a, i + 1), (size_t)(a->len - i) * a->value_size);
    memset(g_coll_value(a, a->len), 0, a->value_size);
    return value;
}
static bool g_coll_remove(g_collection *a, const void *key) {
    bool found;
    int64_t i = g_coll_slot(a, key, &found);
    if (found) {
        a->states[i] = 2; --a->len;
        memset(g_coll_key(a, i), 0, a->key_size);
        if (a->kind == 1) memset(g_coll_value(a, i), 0, a->value_size);
    }
    return found;
}
static void g_coll_clear(g_collection *a) {
    if (a->keys) memset(a->keys, 0, (size_t)a->cap * a->key_size);
    if (a->values) memset(a->values, 0, (size_t)a->cap * a->value_size);
    if (a->states) memset(a->states, 0, (size_t)a->cap);
    a->len = a->used = 0;
}
static g_array g_coll_snapshot(g_collection *a, bool keys, int l, int c) {
    size_t size = keys ? a->key_size : a->value_size;
    g_array out = g_allocate(a->len, size, l, c, keys ? a->key_atomic : a->value_atomic);
    int64_t j = 0;
    for (int64_t i = 0; i < (a->kind == 0 ? a->len : a->cap); ++i)
        if (a->kind == 0 || a->states[i] == 1) {
            memcpy((char *)out.data + (size_t)j++ * size, keys ? g_coll_key(a, i) : g_coll_value(a, i), size);
        }
    return out;
}
static g_collection *g_coll_clone(g_collection *a, int l, int c) {
    g_array keys = {0}, values = {0};
    if (a->kind != 0) keys = g_coll_snapshot(a, true, l, c);
    if (a->kind != 2) values = g_coll_snapshot(a, false, l, c);
    return g_coll_new(a->kind, a->key_kind, a->key_size, a->value_size,
                      a->key_atomic, a->value_atomic, keys, values, l, c);
}
#endif

typedef struct { void (*code)(void); void *env; } g_closure;
static int64_t f_work(int64_t v_x);
static void f_main(void);
static int64_t g_wrap_work(void *env, int64_t v_x) {
    return f_work(v_x);
}
static int64_t f_work(int64_t v_x) {
    int64_t t1 = v_x;
    int64_t t2 = v_x;
    int64_t t3 = INT64_C(1);
    int64_t t4 = g_add(t2, t3, 2, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 14));
    int64_t t5 = v_x;
    int64_t t6 = INT64_C(2);
    int64_t t7 = g_add(t5, t6, 2, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 21));
    int64_t t8[3];
    g_array t9 = (g_array){t8, 3};
    ((int64_t*)t9.data)[0] = t1;
    ((int64_t*)t9.data)[1] = t4;
    ((int64_t*)t9.data)[2] = t7;
    g_array v_a = t9;
    g_array t10 = v_a;
    int64_t t11 = INT64_C(0);
    int64_t t12 = ((int64_t*)t10.data)[t11];
    g_array t13 = v_a;
    int64_t t14 = INT64_C(1);
    int64_t t15 = ((int64_t*)t13.data)[t14];
    int64_t t16 = g_add(t12, t15, 3, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 12));
    g_array t17 = v_a;
    int64_t t18 = INT64_C(2);
    int64_t t19 = ((int64_t*)t17.data)[t18];
    int64_t t20 = g_add(t16, t19, 3, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 19));
    int64_t t21 = INT64_C(100);
    int64_t t22 = INT64_C(25);
    int64_t t23 = (t21 * t22);
    int64_t t24 = g_add(t20, t23, 3, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 26));
    return t24;
}
static void f_main(void) {
    double t25 = g_clock();
    double v_setup = t25;
    int64_t t26 = INT64_C(0);
    int64_t t27 = g_argi(t26, 6, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 8));
    int64_t v_n = t27;
    double t28 = g_clock();
    double t29 = v_setup;
    double t30 = (t28 - t29);
    v_setup = t30;
    double t31 = g_clock();
    double v_start = t31;
    int64_t t32 = INT64_C(0);
    int64_t v_total = t32;
    int64_t t33 = INT64_C(0);
    int64_t v_i = t33;
    while (true) {
        int64_t t34 = v_i;
        int64_t t35 = v_n;
        bool t36 = (t34 < t35);
        if (!t36) break;
        int64_t t37 = v_total;
        int64_t t38 = v_i;
        int64_t t39 = f_work(t38);
        v_total = g_add(t37, t39, 12, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 5));
        int64_t t40 = v_i;
        int64_t t41 = INT64_C(1);
        v_i = g_add(t40, t41, 13, (g_file_json = "\"/Users/igino/glyph/benchmarks/results/macos-arm64-2026-10-28-memory/comparison/sources/checks.gly\"", 5));
    }
    double t42 = g_clock();
    double t43 = v_start;
    double t44 = (t42 - t43);
    double v_elapsed = t44;
    int64_t t45 = v_total;
    g_print_i64(t45);
    double t46 = v_setup;
    g_print_f64(t46);
    double t47 = v_elapsed;
    g_print_f64(t47);
}
int main(int argc, char **argv) {
    g_gc_init(); g_args_init(argc,argv);
    f_main(); return 0;
}
