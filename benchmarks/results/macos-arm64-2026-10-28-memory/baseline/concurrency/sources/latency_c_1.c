typedef struct { g_channel *data,*ack; } context;
static void responder(void *env,void *result) {
    context *ctx=env; int64_t item, i=0;
    while(g_channel_receive(ctx->data,&item)) { g_channel_send(ctx->ack,&i); ++i; }
    *(int64_t*)result=i;
}
int main(int argc,char **argv) {
    g_gc_init(); g_args_init(argc,argv);
    int64_t n=g_argi(0,1,1), item;
    context ctx={g_channel_new(1,sizeof(int64_t),1,1),g_channel_new(1,sizeof(int64_t),1,1)};
    double start=g_clock(); g_scope scope={0}; g_scope_enter(&scope);
    g_task *t=g_spawn(&scope,responder,&ctx,sizeof(int64_t),1,1);
    if(t->error) return 1;
    for(int64_t i=0;i<n;i++) { g_channel_send(ctx.data,&i); g_channel_receive(ctx.ack,&item); }
    g_channel_close(ctx.data);
    if(*(int64_t*)g_task_wait(t,1,1)!=n) return 2;
    g_scope_leave(&scope);
    printf("%lld\n%.17g\n",(long long)n,g_clock()-start); return 0;
}
