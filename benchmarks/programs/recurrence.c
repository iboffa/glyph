#include "common.h"
int main(int argc, char **argv) {
    if(argc!=4) return 1;
    int64_t n=atoll(argv[1]), repeats=atoll(argv[2]), x=atoll(argv[3]);
    if(n<0 || repeats<0 || x<=0 || x>=2147483647) return 1;
    double start=now();
    for(int64_t r=0;r<repeats;r++)
        for(int64_t i=0;i<n;i++) x=x*48271%2147483647;
    double elapsed=now()-start;
    printf("%lld\n%.17g\n",(long long)x,elapsed);
}
