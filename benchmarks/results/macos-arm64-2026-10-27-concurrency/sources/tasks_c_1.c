static void work(void *env,void *result) { (void)env; *(int64_t*)result=42; }
int main(int argc,char **argv) {
    g_gc_init(); g_args_init(argc,argv);
    int64_t n=g_argi(0,1,1), checksum=0;
    double start=g_clock();
    for(int64_t i=0;i<n;i++) {
        g_scope scope={0}; g_scope_enter(&scope);
        g_task *t=g_spawn(&scope,work,NULL,sizeof(int64_t),1,1);
        if(t->error) return 1;
        checksum=g_add(checksum,*(int64_t*)g_task_wait(t,1,1),1,1);
        g_scope_leave(&scope);
    }
    printf("%lld\n%.17g\n",(long long)checksum,g_clock()-start);
    return 0;
}
