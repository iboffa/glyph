/* The harness supplies core/GC headers and, for the parallel variant, the
 * shared scheduler. Checked arithmetic, allocation and scheduling match Glyph. */
static int64_t transform(int64_t x) { return g_std_concat((g_str){"value:",6},g_std_str_i64(x,1,1),1,1).len; }
static void chunk(void *env,g_array input,g_array output,int64_t start,int64_t end) {
    (void)env;
    for(int64_t i=start;i<end;i++) ((int64_t*)output.data)[i]=transform(((int64_t*)input.data)[i]);
}
static g_array sequential(g_array input) {
    g_array output=g_new_atomic(input.len,sizeof(int64_t),1,1);
    chunk(NULL,input,output,0,input.len); return output;
}
int main(int argc,char **argv) {
    g_gc_init(); g_args_init(argc,argv);
    int64_t n=g_argi(0,1,1), repeats=g_argi(1,1,1);
    g_array input=g_range(n,1,1);
    double first=g_clock();
    g_array output=sequential(input);
    first=g_clock()-first;
    double start=g_clock();
    for(int64_t r=0;r<repeats;r++) {
        ((int64_t*)input.data)[0]=r;
        output=sequential(input);
    }
    double elapsed=g_clock()-start;
    printf("%lld\n%.17g\n%.17g\n",(long long)g_sum_i64(output,0,1,1),first,elapsed);
    
    return 0;
}
