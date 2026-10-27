typedef struct { g_channel *channel; int64_t n; } context;
static void producer(void *env,void *result) {
    context *ctx=env;
    for(int64_t i=0;i<ctx->n;i++) g_channel_send(ctx->channel,&i);
    g_channel_close(ctx->channel); *(int64_t*)result=ctx->n;
}
int main(int argc,char **argv) {
    g_gc_init(); g_args_init(argc,argv);
    int64_t n=g_argi(0,1,1), count=0, checksum=0, item;
    g_channel *c=g_channel_new(64,sizeof(int64_t),1,1);
    context ctx={c,n}; double start=g_clock();
    g_scope scope={0}; g_scope_enter(&scope);
    g_task *t=g_spawn(&scope,producer,&ctx,sizeof(int64_t),1,1);
    if(t->error) return 1;
    while(g_channel_receive(c,&item)) { if(item!=count++) return 3; checksum=g_add(checksum,item,1,1); }
    if(*(int64_t*)g_task_wait(t,1,1)!=n) return 2;
    g_scope_leave(&scope);
    printf("%lld\n%.17g\n",(long long)checksum,g_clock()-start);
    return 0;
}
