#ifndef GLYPH_CONCURRENCY_RUNTIME_H
#define GLYPH_CONCURRENCY_RUNTIME_H
#if defined(_WIN32) || (!defined(__APPLE__) && !defined(__linux__))
#error Glyph concurrency requires macOS or Linux pthreads
#endif
#include <pthread.h>
#include <unistd.h>
/* gc.h redirects pthread_create/join to the collector-aware entry points. */
typedef void (*g_map_fn)(void *, g_array, g_array, int64_t, int64_t);
static _Thread_local bool g_worker;
static _Thread_local int g_map_depth;
static struct {
    pthread_mutex_t mutex;
    pthread_cond_t work, done;
    pthread_t threads[31];
    int count, pending;
    unsigned long epoch;
    bool stop, initialized;
    int64_t next, chunk;
    g_map_fn fn;
    void *env;
    g_array input, output;
} g_pool = { .mutex=PTHREAD_MUTEX_INITIALIZER,
             .work=PTHREAD_COND_INITIALIZER, .done=PTHREAD_COND_INITIALIZER };
static int g_env_limit(const char *name, int fallback, int maximum) {
    const char *s=getenv(name);
    if (!s) return fallback;
    char *end; errno=0; long n=strtol(s,&end,10);
    if (errno || !*s || *end || n<1 || n>maximum)
        g_fail("R018","invalid concurrency configuration",1,1);
    return (int)n;
}
static void g_pool_run(void) {
    for (;;) {
        pthread_mutex_lock(&g_pool.mutex);
        int64_t start=g_pool.next, end=start;
        if (start < g_pool.input.len) {
            int64_t remaining=g_pool.input.len-start;
            end=start+(remaining<g_pool.chunk ? remaining : g_pool.chunk);
            g_pool.next=end;
        }
        g_map_fn fn=g_pool.fn;
        void *env=g_pool.env;
        g_array input=g_pool.input, output=g_pool.output;
        pthread_mutex_unlock(&g_pool.mutex);
        if (start==end) return;
        fn(env,input,output,start,end);
    }
}
static void *g_pool_worker(void *unused) {
    (void)unused; g_worker=true;
    unsigned long seen=0;
    pthread_mutex_lock(&g_pool.mutex);
    for (;;) {
        while (!g_pool.stop && seen==g_pool.epoch)
            pthread_cond_wait(&g_pool.work,&g_pool.mutex);
        if (g_pool.stop) break;
        seen=g_pool.epoch;
        pthread_mutex_unlock(&g_pool.mutex);
        g_pool_run();
        pthread_mutex_lock(&g_pool.mutex);
        if (--g_pool.pending==0) pthread_cond_signal(&g_pool.done);
    }
    pthread_mutex_unlock(&g_pool.mutex);
    return NULL;
}
static void g_concurrency_shutdown(void) {
    if (!g_pool.initialized) return;
    pthread_mutex_lock(&g_pool.mutex);
    g_pool.stop=true;
    pthread_cond_broadcast(&g_pool.work);
    pthread_mutex_unlock(&g_pool.mutex);
    for (int i=0;i<g_pool.count;i++) pthread_join(g_pool.threads[i],NULL);
    g_pool.count=0; g_pool.initialized=false;
}
static void g_pool_init(void) {
    if (g_pool.initialized) return; /* Only the main thread enters here. */
    long cpus=sysconf(_SC_NPROCESSORS_ONLN);
    int workers=g_env_limit("GLYPH_WORKERS",cpus<1?1:cpus>8?8:(int)cpus,32);
    g_pool.initialized=true; g_pool.stop=false; g_pool.epoch=0;
    for (int i=1;i<workers;i++) {
        if (pthread_create(&g_pool.threads[g_pool.count],NULL,g_pool_worker,NULL)) {
            g_concurrency_shutdown();
            g_fail("R018","CPU worker creation failed",1,1);
        }
        ++g_pool.count;
    }
}
static g_array g_par_map(g_array input, size_t size, g_map_fn fn, void *env, int l, int c) {
    g_array output=g_new_atomic(input.len,size,l,c);
    if (g_worker || g_map_depth || input.len<1024) {
        ++g_map_depth; fn(env,input,output,0,input.len); --g_map_depth;
        return output;
    }
    g_pool_init();
    if (!g_pool.count) {
        ++g_map_depth; fn(env,input,output,0,input.len); --g_map_depth;
        return output;
    }
    pthread_mutex_lock(&g_pool.mutex);
    g_pool.fn=fn; g_pool.env=env; g_pool.input=input; g_pool.output=output;
    g_pool.next=0; g_pool.chunk=input.len/((g_pool.count+1)*8);
    if (g_pool.chunk<256) g_pool.chunk=256;
    g_pool.pending=g_pool.count;
    ++g_pool.epoch;
    pthread_cond_broadcast(&g_pool.work);
    pthread_mutex_unlock(&g_pool.mutex);
    ++g_map_depth; g_pool_run(); --g_map_depth;
    pthread_mutex_lock(&g_pool.mutex);
    while (g_pool.pending) pthread_cond_wait(&g_pool.done,&g_pool.mutex);
    g_pool.env=NULL; g_pool.input=(g_array){0}; g_pool.output=(g_array){0};
    pthread_mutex_unlock(&g_pool.mutex);
    return output;
}

/* Scoped blocking tasks never occupy CPU pool workers. */
typedef void (*g_task_fn)(void *, void *);
typedef struct g_task {
    struct g_task *next;
    pthread_t thread;
    g_task_fn fn;
    void *env, *result;
    int error;
    bool joined;
} g_task;
typedef struct g_scope { struct g_scope *previous; g_task *tasks; } g_scope;
static _Thread_local g_scope *g_scope_current;
static pthread_mutex_t g_task_mutex=PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t g_task_once=PTHREAD_ONCE_INIT;
static int g_task_limit, g_task_count;
static void g_task_config(void) { g_task_limit=g_env_limit("GLYPH_TASK_LIMIT",64,256); }
static void g_scope_enter(g_scope *scope) {
    scope->previous=g_scope_current; g_scope_current=scope;
}
static void *g_task_start(void *arg) {
    g_task *task=arg; g_worker=true;
    task->fn(task->env,task->result);
    return NULL;
}
static g_task *g_spawn(g_scope *scope, g_task_fn fn, void *env, size_t size, int l, int c) {
    if (!scope) g_fail("R018","spawn outside scope",l,c);
    g_task *task=g_new(1,sizeof(g_task),l,c).data;
    task->fn=fn; task->env=env; task->result=g_new(1,size,l,c).data;
    pthread_once(&g_task_once,g_task_config);
    pthread_mutex_lock(&g_task_mutex);
    if (g_task_count>=g_task_limit) task->error=EAGAIN;
    else ++g_task_count;
    pthread_mutex_unlock(&g_task_mutex);
    if (!task->error) {
        task->error=pthread_create(&task->thread,NULL,g_task_start,task);
        if (task->error) {
            pthread_mutex_lock(&g_task_mutex); --g_task_count; pthread_mutex_unlock(&g_task_mutex);
        } else {
            task->next=scope->tasks; scope->tasks=task;
        }
    }
    return task;
}
static void *g_task_wait(g_task *task, int l, int c) {
    if (!task || task->error) g_fail("R018","wait on failed task",l,c);
    if (!task->joined) {
        if (pthread_join(task->thread,NULL)) g_fail("R018","task join failed",l,c);
        task->joined=true; task->env=NULL;
        pthread_mutex_lock(&g_task_mutex); --g_task_count; pthread_mutex_unlock(&g_task_mutex);
    }
    return task->result;
}
static g_record_IntResult g_task_status(g_task *task) {
    if (task && !task->error) return (g_record_IntResult){true,0,{"",0},{"",0}};
    return (g_record_IntResult){false,task?task->error:EINVAL,{"R018",4},{"task resource or creation failure",32}};
}
static void g_scope_leave(g_scope *scope) {
    for (g_task *task=scope->tasks;task;task=task->next) g_task_wait(task,1,1);
    g_scope_current=scope->previous;
    scope->tasks=NULL;
}

/* Scanned, bounded ring; stack-held send payloads remain rooted while blocked. */
typedef struct {
    pthread_mutex_t mutex;
    pthread_cond_t readable, writable;
    void *buffer;
    size_t size;
    int64_t capacity, head, count;
    bool closed;
} g_channel;
static void g_channel_finalize(void *object, void *unused) {
    (void)unused;
    g_channel *c=object;
    pthread_cond_destroy(&c->readable); pthread_cond_destroy(&c->writable);
    pthread_mutex_destroy(&c->mutex);
}
static g_channel *g_channel_new(int64_t capacity, size_t size, int l, int col) {
    if (capacity<=0) g_fail("R018","channel capacity must be positive",l,col);
    g_channel *c=g_new(1,sizeof(g_channel),l,col).data;
    c->buffer=g_new(capacity,size,l,col).data;
    c->capacity=capacity; c->size=size;
    if (pthread_mutex_init(&c->mutex,NULL)) g_fail("R018","channel mutex creation failed",l,col);
    if (pthread_cond_init(&c->readable,NULL)) {
        pthread_mutex_destroy(&c->mutex); g_fail("R018","channel condition creation failed",l,col);
    }
    if (pthread_cond_init(&c->writable,NULL)) {
        pthread_cond_destroy(&c->readable); pthread_mutex_destroy(&c->mutex);
        g_fail("R018","channel condition creation failed",l,col);
    }
    GC_register_finalizer_no_order(c,g_channel_finalize,NULL,NULL,NULL);
    return c;
}
static bool g_channel_send(g_channel *c, const void *value) {
    pthread_mutex_lock(&c->mutex);
    while (!c->closed && c->count==c->capacity) pthread_cond_wait(&c->writable,&c->mutex);
    bool ok=!c->closed;
    if (ok) {
        /* Avoid head+count signed overflow for very large valid capacities. */
        int64_t tail=c->count>=c->capacity-c->head ? c->count-(c->capacity-c->head) : c->head+c->count;
        memcpy((char*)c->buffer+(size_t)tail*c->size,value,c->size);
        ++c->count; pthread_cond_signal(&c->readable);
    }
    pthread_mutex_unlock(&c->mutex);
    GC_reachable_here(c); GC_reachable_here(value);
    return ok;
}
static bool g_channel_receive(g_channel *c, void *value) {
    pthread_mutex_lock(&c->mutex);
    while (!c->closed && !c->count) pthread_cond_wait(&c->readable,&c->mutex);
    bool ok=c->count!=0;
    if (ok) {
        void *slot=(char*)c->buffer+(size_t)c->head*c->size;
        memcpy(value,slot,c->size); memset(slot,0,c->size);
        if (++c->head==c->capacity) c->head=0;
        --c->count; pthread_cond_signal(&c->writable);
    }
    pthread_mutex_unlock(&c->mutex);
    GC_reachable_here(c);
    return ok;
}
static void g_channel_close(g_channel *c) {
    pthread_mutex_lock(&c->mutex); c->closed=true;
    pthread_cond_broadcast(&c->readable); pthread_cond_broadcast(&c->writable);
    pthread_mutex_unlock(&c->mutex); GC_reachable_here(c);
}
#endif
