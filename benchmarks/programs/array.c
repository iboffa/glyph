#include "common.h"
static int64_t sum(int64_t *a, int64_t n) {
    int64_t s=0;
    for(int64_t i=0;i<n;i++) s+=a[i];
    return s;
}
int main(int argc, char **argv) {
    if(argc!=4) return 1;
    int64_t n=atoll(argv[1]), repeats=atoll(argv[2]), seed=atoll(argv[3]);
    if(n<=0 || n>10000000 || repeats<0 || repeats>10000 || seed<0 || seed>1000) return 1;
    int64_t *a=calloc((size_t)n,sizeof(int64_t));
    if(!a) return 1;
    for(int64_t i=0;i<n;i++) a[i]=(i*17+seed)%1000;
    int64_t checksum=0;
    double start=now();
    for(int64_t r=0;r<repeats;r++) {
        a[r%n]=(a[r%n]+r)%1000;
        checksum+=sum(a,n);
    }
    double elapsed=now()-start;
    printf("%lld\n%.17g\n",(long long)checksum,elapsed);
    free(a);
}
