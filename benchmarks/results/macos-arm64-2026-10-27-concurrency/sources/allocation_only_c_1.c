int main(int argc,char **argv) {
    g_gc_init(); g_args_init(argc,argv);
    int64_t n=g_argi(0,1,1), repeats=g_argi(1,1,1);
    g_array output={0}; double start=g_clock();
    for(int64_t r=0;r<repeats;r++) {
        output=g_new_atomic(n,sizeof(int64_t),1,1);
        for(int64_t i=0;i<n;i++) ((int64_t*)output.data)[i]=1;
    }
    printf("%lld\n%.17g\n",(long long)g_sum_i64(output,0,1,1),g_clock()-start);
    return 0;
}
