#define G_FILE_JSON "\"precise-experiment\""
#include "runtime.h"
#include "precise_gc.h"
typedef struct Node { struct Node *next; int64_t value; } Node;
static const size_t layout[] = {offsetof(Node,next)};
static px_heap heap;
static Node *node(int64_t value) {
#ifdef PRECISE
    Node *p=px_new(&heap,sizeof(Node),layout,1);
#else
    Node *p=g_new(1,sizeof(Node),1,1).data;
#endif
    if (!p) abort(); p->value=value; return p;
}
int main(void) {
    g_gc_init();
    Node *keep=node(73); keep->next=keep;
    /* The only registered root is an interior pointer. Explicit fields preserve
       a cycle; the numeric value is never scanned as a possible reference. */
    void *roots[]={&keep->value};
    double start=g_clock();
    int64_t checksum=0;
    for (int batch=0;batch<1000;++batch) {
        for (int i=0;i<128;++i) { Node *a=node(i),*b=node(i+1); a->next=b;b->next=a;checksum+=b->value; }
#ifdef PRECISE
        px_collect(&heap,roots,1);
        assert(heap.objects==1 && keep->value==73 && keep->next==keep);
#else
        GC_gcollect();
        GC_reachable_here(roots);
        assert(keep->value==73 && keep->next==keep);
#endif
    }
    double elapsed=g_clock()-start;
    checksum += keep->value;
#ifdef PRECISE
    px_collect(&heap,NULL,0); assert(heap.objects==0);
#endif
    printf("%lld\n%.9g\n",(long long)checksum,elapsed);
    return 0;
}
