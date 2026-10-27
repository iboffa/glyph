/* Test-only instrumentation: exercise the shared runtime without exposing
 * synchronization or fault-injection primitives to Glyph programs. */
#define GLYPH_CONCURRENCY 1
#define G_FILE_JSON "\"concurrency harness\""
#include "../glyph/runtime.h"
#include "../glyph/std_runtime.h"
static pthread_mutex_t probe=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t observed=PTHREAD_COND_INITIALIZER;
static pthread_cond_t *watched;
static int waiting, create_attempt, fail_at;
static int tracked_wait(pthread_cond_t *cond, pthread_mutex_t *mutex) {
    pthread_mutex_lock(&probe);
    if (cond==watched) { ++waiting; pthread_cond_broadcast(&observed); }
    pthread_mutex_unlock(&probe);
    return pthread_cond_wait(cond,mutex);
}
static int tracked_create(pthread_t *thread,const pthread_attr_t *attr,
                          void *(*start)(void*),void *arg) {
    if (++create_attempt==fail_at) return EAGAIN;
    return GC_pthread_create(thread,attr,start,arg);
}
#undef pthread_create
#define pthread_create tracked_create
#define pthread_cond_wait tracked_wait
#include "../glyph/concurrency_runtime.h"
#undef pthread_cond_wait
static void observe(pthread_cond_t *cond) {
    pthread_mutex_lock(&probe); watched=cond; waiting=0; pthread_mutex_unlock(&probe);
}
static void await_waiters(int count) {
    pthread_mutex_lock(&probe);
    while(waiting<count) pthread_cond_wait(&observed,&probe);
    pthread_mutex_unlock(&probe);
}
static void send_string(void *env,void *result) {
    g_str value=g_std_concat((g_str){"blocked",7},(g_str){" payload",8},1,1);
    *(bool*)result=g_channel_send(env,&value);
}
static void receive_string(void *env,void *result) {
    g_str value={0}; *(bool*)result=g_channel_receive(env,&value);
}
static void number(void *env,void *result) { (void)env; *(int64_t*)result=42; }
static void check(bool ok) { if(!ok) abort(); }
static void map_identity(void *env,g_array input,g_array output,int64_t start,int64_t end) {
    (void)env;
    for(int64_t i=start;i<end;i++) ((int64_t*)output.data)[i]=((int64_t*)input.data)[i];
}
static void blocked_cleanup(void) { pthread_mutex_lock(&probe); }
static void fatal_child(void *env,void *result) {
    (void)env; (void)result; g_fail("R001","fatal shutdown test",1,1);
}
int main(int argc,char **argv) {
    (void)argv;
    g_gc_init();
    if(argc>1 && argv[1][0]=='f') {
        /* A fatal worker must not call cleanup for main-owned resources. */
        pthread_mutex_lock(&probe); atexit(blocked_cleanup);
        g_scope scope={0}; g_scope_enter(&scope);
        g_task *t=g_spawn(&scope,fatal_child,NULL,sizeof(int64_t),1,1);
        check(!t->error); g_task_wait(t,1,1); return 2;
    }
    if(argc>1) {
        fail_at=2; /* One registered worker must be stopped and joined. */
        g_par_map(g_range(4097,1,1),sizeof(int64_t),map_identity,NULL,1,1);
        return 2;
    }
    for(int cycle=0;cycle<10;cycle++) {
        g_scope scope={0}; g_scope_enter(&scope);
        g_channel *full=g_channel_new(1,sizeof(g_str),1,1);
        g_str seed={"seed",4}; check(g_channel_send(full,&seed));
        observe(&full->writable);
        g_task *a=g_spawn(&scope,send_string,full,sizeof(bool),1,1);
        g_task *b=g_spawn(&scope,send_string,full,sizeof(bool),1,1);
        check(!a->error && !b->error); await_waiters(2);
        GC_gcollect(); g_channel_close(full);
        check(!*(bool*)g_task_wait(a,1,1) && !*(bool*)g_task_wait(b,1,1));
        g_str out={0}; check(g_channel_receive(full,&out) && g_eq(out,seed));
        check(!g_channel_receive(full,&out));
        g_channel *empty=g_channel_new(1,sizeof(g_str),1,1);
        observe(&empty->readable);
        a=g_spawn(&scope,receive_string,empty,sizeof(bool),1,1);
        b=g_spawn(&scope,receive_string,empty,sizeof(bool),1,1);
        check(!a->error && !b->error); await_waiters(2);
        GC_gcollect(); g_channel_close(empty);
        check(!*(bool*)g_task_wait(a,1,1) && !*(bool*)g_task_wait(b,1,1));
        /* The sender's dynamically allocated payload exists solely in its
         * registered blocked stack until the receiver makes room. */
        g_channel *data=g_channel_new(1,sizeof(g_str),1,1);
        check(g_channel_send(data,&seed)); observe(&data->writable);
        a=g_spawn(&scope,send_string,data,sizeof(bool),1,1);
        check(!a->error); await_waiters(1); GC_gcollect();
        check(g_channel_receive(data,&out));
        check(*(bool*)g_task_wait(a,1,1)); GC_gcollect();
        check(g_channel_receive(data,&out));
        check(g_eq(out,(g_str){"blocked payload",15})); g_channel_close(data);
        /* Actual pthread_create failure, after another successful child. */
        a=g_spawn(&scope,number,NULL,sizeof(int64_t),1,1);
        fail_at=create_attempt+1;
        b=g_spawn(&scope,number,NULL,sizeof(int64_t),1,1);
        check(!a->error && b->error==EAGAIN && !g_task_status(b).m_ok);
        fail_at=0; GC_gcollect(); check(*(int64_t*)g_task_wait(a,1,1)==42);
        g_scope_leave(&scope); check(g_task_count==0);
    }
    GC_gcollect(); GC_invoke_finalizers();
    return 0;
}
