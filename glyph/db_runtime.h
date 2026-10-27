#ifndef GLYPH_DB_RUNTIME_H
#define GLYPH_DB_RUNTIME_H
#include <sqlite3.h>
typedef struct g_db_entry { int64_t id; sqlite3 *db; struct g_db_entry *next; } g_db_entry;
typedef struct g_stmt_entry { int64_t id; sqlite3_stmt *stmt; g_db_entry *owner; int state; struct g_stmt_entry *next; } g_stmt_entry;
/* statement states: 0 ready/bindable, 1 row, 2 done/error (reset required). */
static g_db_entry *g_databases;
static g_stmt_entry *g_statements;
static int64_t g_db_serial, g_stmt_serial;
static g_db_entry *g_db_find(int64_t id) {
    for(g_db_entry *e=g_databases;e;e=e->next) if(e->id==id) return e;
    return NULL;
}
static g_stmt_entry *g_stmt_find(int64_t id) {
    for(g_stmt_entry *e=g_statements;e;e=e->next) if(e->id==id) return e;
    return NULL;
}
static g_record_BoolResult g_db_status(sqlite3 *db, int status, int l, int c) {
    if(status==SQLITE_OK) return (g_record_BoolResult){true,true,{"",0},{"",0}};
    const char *message=sqlite3_errmsg(db);
    return (g_record_BoolResult){false,false,{"R015",4},g_text(message,(int64_t)strlen(message),l,c)};
}
static g_record_IntResult g_std_try_db_open(g_str path, int l, int c) {
    if(!path.len || memchr(path.data,0,(size_t)path.len)) return g_error_IntResult("R015","invalid SQLite path");
    if(g_db_serial==INT64_MAX) return g_error_IntResult("R015","database handle IDs exhausted");
    g_db_entry *e=g_new(1,sizeof(*e),l,c).data;
    sqlite3 *db=NULL;
    int status=sqlite3_open_v2(g_cstr(path,l,c),&db,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE,NULL);
    if(status!=SQLITE_OK) {
        g_record_BoolResult error=g_db_status(db,status,l,c);
        if(db) sqlite3_close(db);
        return (g_record_IntResult){false,0,error.m_code,error.m_message};
    }
    sqlite3_busy_timeout(db,5000);
    e->id=++g_db_serial; e->db=db; e->next=g_databases; g_databases=e;
    return (g_record_IntResult){true,e->id,{"",0},{"",0}};
}
static g_record_BoolResult g_std_try_db_close(int64_t id, int l, int c) {
    g_db_entry **link=&g_databases;
    while(*link && (*link)->id!=id) link=&(*link)->next;
    if(!*link) return g_error_BoolResult("R015","invalid or closed database handle");
    g_db_entry *e=*link;
    int status=sqlite3_close(e->db);
    if(status!=SQLITE_OK) return g_db_status(e->db,status,l,c);
    *link=e->next; e->db=NULL; e->next=NULL;
    return (g_record_BoolResult){true,true,{"",0},{"",0}};
}
static g_record_BoolResult g_std_try_db_exec(int64_t id, g_str sql, int l, int c) {
    g_db_entry *e=g_db_find(id);
    if(!e || memchr(sql.data,0,(size_t)sql.len)) return g_error_BoolResult("R015","invalid database handle or SQL text");
    return g_db_status(e->db,sqlite3_exec(e->db,g_cstr(sql,l,c),NULL,NULL,NULL),l,c);
}
static g_record_IntResult g_std_try_db_prepare(int64_t id, g_str sql, int l, int c) {
    g_db_entry *e=g_db_find(id);
    if(!e || sql.len>INT_MAX || memchr(sql.data,0,(size_t)sql.len)) return g_error_IntResult("R015","invalid database handle or SQL text");
    if(g_stmt_serial==INT64_MAX) return g_error_IntResult("R015","statement handle IDs exhausted");
    g_stmt_entry *entry=g_new(1,sizeof(*entry),l,c).data;
    sqlite3_stmt *stmt=NULL; const char *tail=NULL;
    char *text=g_cstr(sql,l,c);
    int status=sqlite3_prepare_v2(e->db,text,(int)sql.len,&stmt,&tail);
    if(status!=SQLITE_OK) {
        g_record_BoolResult error=g_db_status(e->db,status,l,c);
        if(stmt) sqlite3_finalize(stmt);
        return (g_record_IntResult){false,0,error.m_code,error.m_message};
    }
    /* Require exactly one statement; allow only trailing SQL whitespace. */
    while(tail && (*tail==' ' || *tail=='\t' || *tail=='\n' || *tail=='\r' || *tail=='\f')) tail++;
    if(!stmt || (tail && *tail)) { if(stmt) sqlite3_finalize(stmt); return g_error_IntResult("R015","expected one SQLite statement"); }
    entry->id=++g_stmt_serial; entry->stmt=stmt; entry->owner=e;
    entry->next=g_statements; g_statements=entry;
    return (g_record_IntResult){true,entry->id,{"",0},{"",0}};
}
static g_stmt_entry *g_db_binding(int64_t id, int64_t index) {
    g_stmt_entry *e=g_stmt_find(id);
    if(!e || e->state!=0 || index<1 || index>sqlite3_bind_parameter_count(e->stmt)) return NULL;
    return e;
}
static g_record_BoolResult g_std_try_db_bind_int(int64_t id, int64_t index, int64_t value, int l, int c) {
    g_stmt_entry *e=g_db_binding(id,index);
    if(!e) return g_error_BoolResult("R015","invalid statement state or parameter index");
    return g_db_status(e->owner->db,sqlite3_bind_int64(e->stmt,(int)index,value),l,c);
}
static g_record_BoolResult g_std_try_db_bind_float(int64_t id, int64_t index, double value, int l, int c) {
    g_stmt_entry *e=g_db_binding(id,index);
    if(!e || !isfinite(value)) return g_error_BoolResult("R015","invalid binding or nonfinite float");
    return g_db_status(e->owner->db,sqlite3_bind_double(e->stmt,(int)index,value),l,c);
}
static g_record_BoolResult g_std_try_db_bind_text(int64_t id, int64_t index, g_str value, int l, int c) {
    g_stmt_entry *e=g_db_binding(id,index);
    if(!e || value.len>INT_MAX) return g_error_BoolResult("R015","invalid statement binding or text size");
    return g_db_status(e->owner->db,sqlite3_bind_text(e->stmt,(int)index,value.data,(int)value.len,SQLITE_TRANSIENT),l,c);
}
static g_record_BoolResult g_std_try_db_bind_bytes(int64_t id, int64_t index, g_array value, int l, int c) {
    g_stmt_entry *e=g_db_binding(id,index);
    if(!e || value.len>INT_MAX || !g_bytes_valid(value)) return g_error_BoolResult("R015","invalid statement binding or bytes");
    char *bytes=g_new_atomic(value.len,1,l,c).data;
    for(int64_t i=0;i<value.len;i++) bytes[i]=(char)((int64_t*)value.data)[i];
    return g_db_status(e->owner->db,sqlite3_bind_blob(e->stmt,(int)index,bytes,(int)value.len,SQLITE_TRANSIENT),l,c);
}
static g_record_BoolResult g_std_try_db_bind_null(int64_t id, int64_t index, int l, int c) {
    g_stmt_entry *e=g_db_binding(id,index);
    if(!e) return g_error_BoolResult("R015","invalid statement state or parameter index");
    return g_db_status(e->owner->db,sqlite3_bind_null(e->stmt,(int)index),l,c);
}
static g_record_BoolResult g_std_try_db_step(int64_t id, int l, int c) {
    g_stmt_entry *e=g_stmt_find(id);
    if(!e || e->state==2) return g_error_BoolResult("R015","invalid statement or reset required");
    int status=sqlite3_step(e->stmt);
    e->state=status==SQLITE_ROW ? 1 : 2;
    if(status==SQLITE_ROW || status==SQLITE_DONE)
        return (g_record_BoolResult){true,status==SQLITE_ROW,{"",0},{"",0}};
    return g_db_status(e->owner->db,status,l,c);
}
static g_record_BoolResult g_std_try_db_reset(int64_t id, int l, int c) {
    g_stmt_entry *e=g_stmt_find(id);
    if(!e) return g_error_BoolResult("R015","invalid statement handle");
    int status=sqlite3_reset(e->stmt); e->state=0;
    return g_db_status(e->owner->db,status,l,c);
}
static g_record_BoolResult g_std_try_db_finalize(int64_t id, int l, int c) {
    g_stmt_entry **link=&g_statements;
    while(*link && (*link)->id!=id) link=&(*link)->next;
    if(!*link) return g_error_BoolResult("R015","invalid or finalized statement handle");
    g_stmt_entry *e=*link; *link=e->next;
    int status=sqlite3_finalize(e->stmt);
    g_record_BoolResult result=g_db_status(e->owner->db,status,l,c);
    e->stmt=NULL; e->owner=NULL; e->next=NULL;
    return result;
}
static g_stmt_entry *g_db_column(int64_t id, int64_t column, bool require_row) {
    g_stmt_entry *e=g_stmt_find(id);
    if(!e || (require_row && e->state!=1) || column<0 || column>=sqlite3_column_count(e->stmt)) return NULL;
    return e;
}
static g_record_IntResult g_std_try_db_columns(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_stmt_entry *e=g_stmt_find(id);
    if(!e) return g_error_IntResult("R015","invalid statement handle");
    return (g_record_IntResult){true,sqlite3_column_count(e->stmt),{"",0},{"",0}};
}
static g_record_StringResult g_std_try_db_column_name(int64_t id, int64_t column, int l, int c) {
    g_stmt_entry *e=g_db_column(id,column,false);
    if(!e) return g_error_StringResult("R015","invalid statement or column index");
    const char *name=sqlite3_column_name(e->stmt,(int)column);
    if(!name) return g_error_StringResult("R015","cannot read column name");
    g_str text={name,(int64_t)strlen(name)};
    if(!g_utf8(text)) return g_error_StringResult("R015","column name is not UTF-8");
    return (g_record_StringResult){true,g_text(text.data,text.len,l,c),{"",0},{"",0}};
}
static g_record_StringResult g_std_try_db_column_type(int64_t id, int64_t column, int l, int c) {
    (void)l; (void)c;
    g_stmt_entry *e=g_db_column(id,column,true);
    if(!e) return g_error_StringResult("R015","no current row or invalid column index");
    const char *types[]={"", "int", "float", "text", "bytes", "null"};
    const char *name=types[sqlite3_column_type(e->stmt,(int)column)];
    return (g_record_StringResult){true,{name,(int64_t)strlen(name)},{"",0},{"",0}};
}
static g_record_IntResult g_std_try_db_column_int(int64_t id, int64_t column, int l, int c) {
    (void)l; (void)c;
    g_stmt_entry *e=g_db_column(id,column,true);
    if(!e || sqlite3_column_type(e->stmt,(int)column)!=SQLITE_INTEGER) return g_error_IntResult("R015","column is not an integer or no current row");
    return (g_record_IntResult){true,sqlite3_column_int64(e->stmt,(int)column),{"",0},{"",0}};
}
static g_record_FloatResult g_std_try_db_column_float(int64_t id, int64_t column, int l, int c) {
    (void)l; (void)c;
    g_stmt_entry *e=g_db_column(id,column,true);
    if(!e || sqlite3_column_type(e->stmt,(int)column)!=SQLITE_FLOAT) return g_error_FloatResult("R015","column is not a float or no current row");
    double value=sqlite3_column_double(e->stmt,(int)column);
    if(!isfinite(value)) return g_error_FloatResult("R015","SQLite value is not finite");
    return (g_record_FloatResult){true,value,{"",0},{"",0}};
}
static g_record_StringResult g_std_try_db_column_text(int64_t id, int64_t column, int l, int c) {
    g_stmt_entry *e=g_db_column(id,column,true);
    if(!e || sqlite3_column_type(e->stmt,(int)column)!=SQLITE_TEXT) return g_error_StringResult("R015","column is not text or no current row");
    const char *data=(const char*)sqlite3_column_text(e->stmt,(int)column);
    if(!data) return g_error_StringResult("R015","cannot read SQLite text");
    g_str text={data,sqlite3_column_bytes(e->stmt,(int)column)};
    if(!g_utf8(text)) return g_error_StringResult("R015","SQLite text is not UTF-8");
    return (g_record_StringResult){true,g_text(text.data,text.len,l,c),{"",0},{"",0}};
}
static g_record_BytesResult g_std_try_db_column_bytes(int64_t id, int64_t column, int l, int c) {
    g_stmt_entry *e=g_db_column(id,column,true);
    if(!e || sqlite3_column_type(e->stmt,(int)column)!=SQLITE_BLOB) return g_error_BytesResult("R015","column is not bytes or no current row");
    const char *data=sqlite3_column_blob(e->stmt,(int)column);
    int size=sqlite3_column_bytes(e->stmt,(int)column);
    if(!data && size) return g_error_BytesResult("R015","cannot read SQLite bytes");
    return (g_record_BytesResult){true,g_std_encode_utf8((g_str){data,size},l,c),{"",0},{"",0}};
}
static g_record_IntResult g_std_try_db_changes(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_db_entry *e=g_db_find(id);
    if(!e) return g_error_IntResult("R015","invalid database handle");
    return (g_record_IntResult){true,sqlite3_changes(e->db),{"",0},{"",0}};
}
static g_record_IntResult g_std_try_db_last_id(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_db_entry *e=g_db_find(id);
    if(!e) return g_error_IntResult("R015","invalid database handle");
    return (g_record_IntResult){true,sqlite3_last_insert_rowid(e->db),{"",0},{"",0}};
}
#endif
