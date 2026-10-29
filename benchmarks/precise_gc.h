/* Experimental, single-threaded, nonmoving layout/explicit-root collector.
 * Not a Glyph runtime backend: there is no emitted root-stack/safepoint ABI yet.
 * A linear interior-pointer lookup deliberately favors auditability over speed.
 */
#ifndef GLYPH_PRECISE_EXPERIMENT
#define GLYPH_PRECISE_EXPERIMENT
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include <assert.h>
typedef struct px_object {
    struct px_object *next;
    size_t bytes, fields;
    const size_t *offsets;
    unsigned mark;
    max_align_t align;
    unsigned char data[];
} px_object;
typedef struct { px_object *head; size_t bytes, objects; } px_heap;
static void *px_new(px_heap *h, size_t bytes, const size_t *offsets, size_t fields) {
    if (bytes > SIZE_MAX - sizeof(px_object)) return NULL;
    for (size_t i=0;i<fields;++i) if (bytes < sizeof(void*) || offsets[i] > bytes-sizeof(void*)) return NULL;
    px_object *o = calloc(1, sizeof(*o) + (bytes ? bytes : 1));
    if (!o) return NULL;
    o->next=h->head; o->bytes=bytes; o->fields=fields; o->offsets=offsets;
    h->head=o; h->bytes+=bytes; ++h->objects; return o->data;
}
static px_object *px_find(px_heap *h, const void *p) {
    uintptr_t address=(uintptr_t)p;
    for (px_object *o=h->head;o;o=o->next) {
        uintptr_t start=(uintptr_t)o->data;
        if (address>=start && address-start<=o->bytes) return o; /* includes one-past */
    }
    return NULL;
}
static void px_collect(px_heap *h, void *const *roots, size_t count) {
    /* Worklist capacity equals the object count; each object enters once. */
    px_object **work=malloc((h->objects ? h->objects : 1)*sizeof(*work));
    if (!work) abort();
    size_t pending=0;
    for (size_t i=0;i<count;++i) {
        px_object *o=px_find(h,roots[i]);
        if (o && !o->mark) { o->mark=1; work[pending++]=o; }
    }
    while (pending) {
        px_object *o=work[--pending];
        for (size_t i=0;i<o->fields;++i) {
            void *p; memcpy(&p,o->data+o->offsets[i],sizeof p);
            px_object *child=px_find(h,p);
            if (child && !child->mark) { child->mark=1; work[pending++]=child; }
        }
    }
    free(work);
    px_object **link=&h->head;
    while (*link) {
        px_object *o=*link;
        if (!o->mark) { *link=o->next; h->bytes-=o->bytes; --h->objects; free(o); }
        else { o->mark=0; link=&o->next; }
    }
}
#endif
