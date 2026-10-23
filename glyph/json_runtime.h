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
    return root ? g_json_success(root->raw) : g_error_StringResult("R011",error);
}
static g_record_StringResult g_std_try_json_kind(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R011",error);
    const char *names[]={"null","bool","number","string","array","object"};
    const char *name=names[root->kind];
    return g_json_success((g_str){name,(int64_t)strlen(name)});
}
static g_record_StringResult g_std_try_json_string(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R011",error);
    if(root->kind!=G_JSON_STRING) return g_error_StringResult("R011","expected JSON string");
    return g_json_success(root->text);
}
static g_record_StringResult g_std_try_json_get(g_str source, g_str key, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R011",error);
    if(root->kind!=G_JSON_OBJECT) return g_error_StringResult("R011","expected JSON object");
    g_json_node *found=NULL;
    for(g_json_node *n=root->child;n;n=n->next) if(g_eq(n->key,key)) found=n;
    return found ? g_json_success(found->raw) : g_error_StringResult("R011","JSON key not found");
}
static g_record_StringResult g_std_try_json_at(g_str source, int64_t index, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringResult("R011",error);
    if(root->kind!=G_JSON_ARRAY) return g_error_StringResult("R011","expected JSON array");
    if(index<0 || index>=root->count) return g_error_StringResult("R011","JSON index out of bounds");
    g_json_node *n=root->child;
    while(index--) n=n->next;
    return g_json_success(n->raw);
}
static g_record_IntResult g_std_try_json_len(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_IntResult("R011",error);
    if(root->kind!=G_JSON_ARRAY && root->kind!=G_JSON_OBJECT) return g_error_IntResult("R011","expected JSON array or object");
    return (g_record_IntResult){true,root->count,{"",0},{"",0}};
}
static g_record_StringsResult g_std_try_json_keys(g_str source, int l, int c) {
    const char *error;
    g_json_node *root=g_json_parse(source,&error,l,c);
    if(!root) return g_error_StringsResult("R011",error);
    if(root->kind!=G_JSON_OBJECT) return g_error_StringsResult("R011","expected JSON object");
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
    if(object && keys.len!=values.len) return g_error_StringResult("R011","JSON keys and values have different lengths");
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
