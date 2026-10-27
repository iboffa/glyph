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
