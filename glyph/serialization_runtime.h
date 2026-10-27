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
