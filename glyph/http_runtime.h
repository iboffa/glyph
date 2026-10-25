#ifndef GLYPH_HTTP_RUNTIME_H
#define GLYPH_HTTP_RUNTIME_H
#include <curl/curl.h>
typedef struct { char *data; size_t len, capacity, limit; bool failed; } g_http_buffer;
static size_t g_http_append(char *data, size_t size, size_t count, void *context) {
    g_http_buffer *b=context;
    if(size && count>SIZE_MAX/size) { b->failed=true; return 0; }
    size_t n=size*count;
    if(n>b->limit-b->len) { b->failed=true; return 0; }
    size_t needed=b->len+n;
    if(needed>b->capacity) {
        size_t capacity=b->capacity ? b->capacity : 4096;
        while(capacity<needed) { if(capacity>SIZE_MAX/2) { capacity=needed; break; } capacity*=2; }
        if(capacity>b->limit) capacity=b->limit;
        char *next=realloc(b->data,capacity);
        if(!next) { b->failed=true; return 0; }
        b->data=next; b->capacity=capacity;
    }
    if(n) memcpy(b->data+b->len,data,n);
    b->len=needed; return n;
}
static bool g_http_header_name(g_str s, int64_t length, const char *name) {
    if(length!=(int64_t)strlen(name)) return false;
    for(int64_t i=0;i<length;i++) {
        char b=s.data[i]; if(b>='A' && b<='Z') b+=(char)32;
        if(b!=name[i]) return false;
    }
    return true;
}
static g_record_HttpResult g_std_try_http_request(g_str method, g_str url, g_array headers,
        g_array body, int64_t timeout, int64_t limit, g_str ca_file, int l, int c) {
    const char *verbs[]={"GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"};
    bool valid_method=false;
    for(size_t i=0;i<sizeof verbs/sizeof *verbs;i++)
        if(g_eq(method,(g_str){verbs[i],(int64_t)strlen(verbs[i])})) valid_method=true;
    bool valid_url=(url.len>=7 && !memcmp(url.data,"http://",7)) || (url.len>=8 && !memcmp(url.data,"https://",8));
    if(!valid_method || !valid_url || timeout<=0 || timeout>LONG_MAX || limit<0 || (uint64_t)limit>SIZE_MAX ||
       memchr(url.data,0,(size_t)url.len) || memchr(ca_file.data,0,(size_t)ca_file.len) || !g_bytes_valid(body))
        return g_error_HttpResult("invalid HTTP method, URL, bytes, timeout, limit or CA path");
    if(g_eq(method,(g_str){"HEAD",4}) && body.len) return g_error_HttpResult("HEAD requests cannot have a body");
    for(int64_t i=0;i<headers.len;i++) {
        g_str h=((g_str*)headers.data)[i];
        int64_t colon=0;
        while(colon<h.len && h.data[colon]!=':') {
            unsigned char b=(unsigned char)h.data[colon];
            if(!((b>='a' && b<='z') || (b>='A' && b<='Z') || (b>='0' && b<='9') || strchr("!#$%&'*+-.^_`|~",b)))
                return g_error_HttpResult("invalid HTTP header name");
            colon++;
        }
        if(!colon || colon==h.len || memchr(h.data,0,(size_t)h.len) || memchr(h.data,'\r',(size_t)h.len) || memchr(h.data,'\n',(size_t)h.len))
            return g_error_HttpResult("invalid HTTP header");
        for(int64_t j=colon+1;j<h.len;j++) {
            unsigned char b=(unsigned char)h.data[j];
            if((b<32 && b!='\t') || b==127) return g_error_HttpResult("invalid HTTP header control character");
        }
        if(g_http_header_name(h,colon,"content-length") || g_http_header_name(h,colon,"transfer-encoding"))
            return g_error_HttpResult("HTTP body framing headers are managed by the runtime");
    }
    static bool initialized;
    if(!initialized) {
        if(curl_global_init(CURL_GLOBAL_DEFAULT)!=CURLE_OK) return g_error_HttpResult("cannot initialize HTTP library");
        initialized=true; atexit(curl_global_cleanup);
    }
    CURL *curl=curl_easy_init();
    if(!curl) return g_error_HttpResult("cannot allocate HTTP request");
    struct curl_slist *list=NULL;
    g_http_buffer response={NULL,0,0,(size_t)limit,false}, received_headers={NULL,0,0,65536,false};
    CURLcode code=CURLE_OK;
    for(int64_t i=0;i<headers.len;i++) {
        struct curl_slist *next=curl_slist_append(list,g_cstr(((g_str*)headers.data)[i],l,c));
        if(!next) { code=CURLE_OUT_OF_MEMORY; goto finish; } list=next;
    }
#define G_HTTP_SET(option,value) do { code=curl_easy_setopt(curl,option,value); if(code!=CURLE_OK) goto finish; } while(0)
    G_HTTP_SET(CURLOPT_URL,g_cstr(url,l,c));
    G_HTTP_SET(CURLOPT_PROTOCOLS,(long)(CURLPROTO_HTTP|CURLPROTO_HTTPS));
    G_HTTP_SET(CURLOPT_FOLLOWLOCATION,0L);
    G_HTTP_SET(CURLOPT_SSL_VERIFYPEER,1L);
    G_HTTP_SET(CURLOPT_SSL_VERIFYHOST,2L);
    G_HTTP_SET(CURLOPT_NOSIGNAL,1L);
    G_HTTP_SET(CURLOPT_TIMEOUT_MS,(long)timeout);
    G_HTTP_SET(CURLOPT_CONNECTTIMEOUT_MS,(long)timeout);
    if(ca_file.len) G_HTTP_SET(CURLOPT_CAINFO,g_cstr(ca_file,l,c));
    G_HTTP_SET(CURLOPT_HTTPHEADER,list);
    G_HTTP_SET(CURLOPT_WRITEFUNCTION,g_http_append);
    G_HTTP_SET(CURLOPT_WRITEDATA,&response);
    G_HTTP_SET(CURLOPT_HEADERFUNCTION,g_http_append);
    G_HTTP_SET(CURLOPT_HEADERDATA,&received_headers);
    if(body.len || g_eq(method,(g_str){"POST",4}) || g_eq(method,(g_str){"PUT",3}) || g_eq(method,(g_str){"PATCH",5})) {
        char *bytes=g_new_atomic(body.len,1,l,c).data;
        for(int64_t i=0;i<body.len;i++) bytes[i]=(char)((int64_t*)body.data)[i];
        G_HTTP_SET(CURLOPT_POSTFIELDSIZE_LARGE,(curl_off_t)body.len);
        /* COPYPOSTFIELDS keeps the request alive without depending on GC roots inside libcurl. */
        G_HTTP_SET(CURLOPT_COPYPOSTFIELDS,bytes);
    }
    if(g_eq(method,(g_str){"HEAD",4})) G_HTTP_SET(CURLOPT_NOBODY,1L);
    G_HTTP_SET(CURLOPT_CUSTOMREQUEST,g_cstr(method,l,c));
    code=curl_easy_perform(curl);
finish:;
    long status=0;
    if(code==CURLE_OK) code=curl_easy_getinfo(curl,CURLINFO_RESPONSE_CODE,&status);
    curl_slist_free_all(list); curl_easy_cleanup(curl);
    g_record_HttpResult result;
    if(code!=CURLE_OK) result=g_error_HttpResult(response.failed || received_headers.failed ? "HTTP response limit or allocation failure" : curl_easy_strerror(code));
    else result=(g_record_HttpResult){true,
        g_std_encode_utf8((g_str){response.data,(int64_t)response.len},l,c),{"",0},{"",0},(int64_t)status,
        g_std_encode_utf8((g_str){received_headers.data,(int64_t)received_headers.len},l,c)};
    free(response.data); free(received_headers.data);
    return result;
#undef G_HTTP_SET
}
#endif
