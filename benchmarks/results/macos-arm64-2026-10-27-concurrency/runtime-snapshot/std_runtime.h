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
