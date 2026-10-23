#define _DARWIN_C_SOURCE
#define G_FILE_JSON "\042\143\171\143\154\145\163\056\147\154\171\042"
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
#undef G_RESULT_TYPE

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
    FILE *f=fopen(g_cstr(path,l,c),"rb");
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
    FILE *f=fopen(g_cstr(path,l,c),"wb");
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
    struct stat x,y;
    return !stat(g_cstr(a,l,c),&x) && !stat(g_cstr(b,l,c),&y) &&
        x.st_dev==y.st_dev && x.st_ino==y.st_ino;
}
static bool g_std_file_exists(g_str path, int l, int c) {
    struct stat info;
    return !stat(g_cstr(path,l,c), &info) && S_ISREG(info.st_mode);
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

typedef struct g_record_Node g_record_Node;
struct g_record_Node {
    g_array m_links;
    int64_t m_value;
};
static int64_t f_work(int64_t v_seed);
static void f_main(void);
static int64_t f_work(int64_t v_seed) {
    int64_t t1 = INT64_C(0);
    int64_t v_i = t1;
    int64_t t2 = INT64_C(0);
    int64_t v_total = t2;
    while (true) {
        int64_t t3 = v_i;
        int64_t t4 = INT64_C(64);
        bool t5 = (t3 < t4);
        if (!t5) break;
        g_array t6 = g_new(0, sizeof(g_record_Node), 8, 16);
        int64_t t7 = v_seed;
        g_record_Node t8 = (g_record_Node){t6, t7};
        g_array t9 = g_new(1, sizeof(g_record_Node), 8, 10);
        ((g_record_Node*)t9.data)[0] = t8;
        g_array v_a = t9;
        g_array t10 = v_a;
        int64_t t11 = v_i;
        g_record_Node t12 = (g_record_Node){t10, t11};
        g_array t13 = g_new(1, sizeof(g_record_Node), 9, 10);
        ((g_record_Node*)t13.data)[0] = t12;
        g_array v_b = t13;
        g_array t14 = v_a;
        int64_t t15 = INT64_C(0);
        int64_t t16 = g_index(t14, t15, 10, 5);
        g_array t17 = v_b;
        (((g_record_Node*)t14.data)[t16]).m_links = t17;
        int64_t t18 = v_total;
        g_array t19 = v_a;
        int64_t t20 = INT64_C(0);
        int64_t t21 = g_index(t19, t20, 11, 14);
        g_record_Node t22 = ((g_record_Node*)t19.data)[t21];
        g_array t23 = t22.m_links;
        int64_t t24 = INT64_C(0);
        int64_t t25 = g_index(t23, t24, 11, 19);
        g_record_Node t26 = ((g_record_Node*)t23.data)[t25];
        g_array t27 = t26.m_links;
        int64_t t28 = INT64_C(0);
        int64_t t29 = g_index(t27, t28, 11, 28);
        g_record_Node t30 = ((g_record_Node*)t27.data)[t29];
        int64_t t31 = t30.m_value;
        v_total = g_add(t18, t31, 11, 5);
        int64_t t32 = v_i;
        int64_t t33 = INT64_C(1);
        v_i = g_add(t32, t33, 12, 5);
    }
    int64_t t34 = v_total;
    return t34;
}
static void f_main(void) {
    return ;
}

#include <sys/resource.h>
static int compare_double(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static uint64_t peak_rss(void) {
    struct rusage r;
    if (getrusage(RUSAGE_SELF, &r)) abort();
#ifdef __APPLE__
    return (uint64_t)r.ru_maxrss;
#else
    return (uint64_t)r.ru_maxrss * 1024;
#endif
}

int main(int argc, char **argv) {
    g_gc_init();
    g_argc = argc; g_argv = argv;
    int64_t n = g_argi(0, 1, 1);
    if (n < 32 || n > 65536) return 2;
    double *latencies = malloc((size_t)n * sizeof(double));
    if (!latencies) return 3;
    
    int64_t checksum = 0;
    double start = g_clock();
    for (int64_t i = 0; i < n; ++i) {
        double before = g_clock();
        checksum += f_work(i);
        latencies[i] = g_clock() - before;
    }
    double elapsed = g_clock() - start;
    int64_t retained = 0;
    uint64_t rss = peak_rss();
    size_t heap = 0, heap_after = 0, free_after = 0, collections = 0;
#if 1
    heap = GC_get_heap_size();
    collections = GC_get_gc_no();
    GC_gcollect();
    heap_after = GC_get_heap_size(); free_after = GC_get_free_bytes();
#endif
    qsort(latencies, (size_t)n, sizeof(double), compare_double);
    printf("{\"checksum\":%lld,\"retained\":%lld,\"elapsed_s\":%.9g,"
           "\"peak_rss_bytes\":%llu,\"gc_total_allocated_bytes\":%llu,"
           "\"batch_p50_s\":%.9g,\"batch_p99_s\":%.9g,\"batch_max_s\":%.9g,"
           "\"gc_heap_bytes\":%zu,\"gc_collections\":%zu,"
           "\"gc_heap_after_collect_bytes\":%zu,\"gc_free_after_collect_bytes\":%zu}\n",
           (long long)checksum, (long long)retained, elapsed,
           (unsigned long long)rss, (unsigned long long)GC_get_total_bytes(),
           latencies[n/2],
           latencies[(n*99-1)/100], latencies[n-1], heap, collections, heap_after, free_after);
    free(latencies);
    return 0;
}
