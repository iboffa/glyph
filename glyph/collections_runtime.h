#ifndef GLYPH_COLLECTIONS_RUNTIME_H
#define GLYPH_COLLECTIONS_RUNTIME_H
/* Shared, GC-owned headers. No backing-storage pointers escape to Glyph. */
typedef struct {
    int kind, key_kind; /* list=0, map=1, set=2; key: int=0, bool=1, str=2 */
    int64_t len, cap, used;
    size_t key_size, value_size;
    bool key_atomic, value_atomic;
    void *keys, *values;
    unsigned char *states; /* empty=0, occupied=1, deleted=2 */
} g_collection;

static void *g_coll_bytes(int64_t n, size_t size, bool atomic, int l, int c) {
    return g_allocate(n, size, l, c, atomic).data;
}
static uint64_t g_coll_hash(g_collection *a, const void *key) {
    if (a->key_kind == 2) {
        g_str s = *(const g_str *)key;
        uint64_t h = UINT64_C(14695981039346656037);
        for (int64_t i = 0; i < s.len; ++i) h = (h ^ (unsigned char)s.data[i]) * UINT64_C(1099511628211);
        return h;
    }
    uint64_t x = a->key_kind == 1 ? *(const bool *)key : (uint64_t)*(const int64_t *)key;
    x ^= x >> 30; x *= UINT64_C(0xbf58476d1ce4e5b9);
    x ^= x >> 27; x *= UINT64_C(0x94d049bb133111eb);
    return x ^ (x >> 31);
}
static bool g_coll_equal(g_collection *a, const void *x, const void *y) {
    if (a->key_kind == 2) return g_eq(*(const g_str *)x, *(const g_str *)y);
    if (a->key_kind == 1) return *(const bool *)x == *(const bool *)y;
    return *(const int64_t *)x == *(const int64_t *)y;
}
static void *g_coll_key(g_collection *a, int64_t i) { return (char *)a->keys + (size_t)i * a->key_size; }
static void *g_coll_value(g_collection *a, int64_t i) { return (char *)a->values + (size_t)i * a->value_size; }
static int64_t g_coll_slot(g_collection *a, const void *key, bool *found) {
    int64_t i = (int64_t)(g_coll_hash(a, key) & (uint64_t)(a->cap - 1)), deleted = -1;
    while (a->states[i]) {
        if (a->states[i] == 1 && g_coll_equal(a, key, g_coll_key(a, i))) { *found = true; return i; }
        if (a->states[i] == 2 && deleted < 0) deleted = i;
        i = (i + 1) & (a->cap - 1);
    }
    *found = false;
    return deleted >= 0 ? deleted : i;
}
static void g_coll_resize(g_collection *a, int64_t cap, int l, int c) {
    if (a->kind == 0) {
        void *values = g_coll_bytes(cap, a->value_size, a->value_atomic, l, c);
        if (a->len) memcpy(values, a->values, (size_t)a->len * a->value_size);
        a->values = values; a->cap = cap;
        return;
    }
    g_collection old = *a;
    a->keys = g_coll_bytes(cap, a->key_size, a->key_atomic, l, c);
    if (a->kind == 1) a->values = g_coll_bytes(cap, a->value_size, a->value_atomic, l, c);
    a->states = g_coll_bytes(cap, 1, true, l, c);
    a->cap = cap; a->used = a->len;
    for (int64_t i = 0; i < old.cap; ++i) if (old.states[i] == 1) {
        bool found;
        int64_t j = g_coll_slot(a, g_coll_key(&old, i), &found);
        a->states[j] = 1;
        memcpy(g_coll_key(a, j), g_coll_key(&old, i), a->key_size);
        if (a->kind == 1) memcpy(g_coll_value(a, j), g_coll_value(&old, i), a->value_size);
    }
}
static bool g_coll_put(g_collection *a, const void *key, const void *value, int l, int c) {
    bool found;
    int64_t i = g_coll_slot(a, key, &found);
    if (!found) {
        /* Keep an empty slot; rebuild tombstones without unnecessary growth. */
        if (a->used >= a->cap - a->cap / 4) {
            int64_t cap = a->len < a->cap / 2 ? a->cap : g_mul(a->cap, 2, l, c);
            g_coll_resize(a, cap, l, c);
            i = g_coll_slot(a, key, &found);
        }
        if (!a->states[i]) ++a->used;
        a->states[i] = 1; ++a->len;
        memcpy(g_coll_key(a, i), key, a->key_size);
    }
    if (a->kind == 1) memcpy(g_coll_value(a, i), value, a->value_size);
    return !found;
}
static g_collection *g_coll_new(int kind, int key_kind, size_t key_size, size_t value_size,
                                bool key_atomic, bool value_atomic, g_array keys, g_array values, int l, int c) {
    if (kind == 1 && keys.len != values.len) g_fail("R007", "map key/value arrays must have equal lengths", l, c);
    g_collection *a = g_coll_bytes(1, sizeof(*a), false, l, c);
    a->kind = kind; a->key_kind = key_kind; a->key_size = key_size; a->value_size = value_size;
    a->key_atomic = key_atomic; a->value_atomic = value_atomic;
    g_coll_resize(a, kind == 0 && values.len > 8 ? values.len : 8, l, c);
    if (kind == 0) {
        a->len = values.len;
        if (values.len) memcpy(a->values, values.data, (size_t)values.len * value_size);
    } else {
        for (int64_t i = 0; i < keys.len; ++i)
            g_coll_put(a, (char *)keys.data + (size_t)i * key_size,
                       kind == 1 ? (char *)values.data + (size_t)i * value_size : NULL, l, c);
    }
    return a;
}
static int64_t g_coll_index(g_collection *a, int64_t i, int l, int c) {
    if (i < 0 || i >= a->len) g_fail("R003", "list index out of bounds", l, c);
    return i;
}
static void *g_coll_get(g_collection *a, const void *key, const void *fallback, int l, int c) {
    if (a->kind == 0) return g_coll_value(a, g_coll_index(a, *(const int64_t *)key, l, c));
    bool found;
    int64_t i = g_coll_slot(a, key, &found);
    if (found) return g_coll_value(a, i);
    if (fallback) return (void *)fallback;
    g_fail("R011", "map key not found", l, c);
    return NULL;
}
static bool g_coll_contains(g_collection *a, const void *key) {
    bool found; g_coll_slot(a, key, &found); return found;
}
static void g_coll_append(g_collection *a, const void *value, int l, int c) {
    if (a->len == a->cap) g_coll_resize(a, g_mul(a->cap, 2, l, c), l, c);
    memcpy(g_coll_value(a, a->len++), value, a->value_size);
}
static void g_coll_set(g_collection *a, int64_t i, const void *value, int l, int c) {
    memcpy(g_coll_value(a, g_coll_index(a, i, l, c)), value, a->value_size);
}
static void *g_coll_take(g_collection *a, int64_t i, int l, int c) {
    g_coll_index(a, i, l, c);
    void *value = g_coll_bytes(1, a->value_size, a->value_atomic, l, c);
    memcpy(value, g_coll_value(a, i), a->value_size);
    --a->len;
    memmove(g_coll_value(a, i), g_coll_value(a, i + 1), (size_t)(a->len - i) * a->value_size);
    memset(g_coll_value(a, a->len), 0, a->value_size);
    return value;
}
static bool g_coll_remove(g_collection *a, const void *key) {
    bool found;
    int64_t i = g_coll_slot(a, key, &found);
    if (found) {
        a->states[i] = 2; --a->len;
        memset(g_coll_key(a, i), 0, a->key_size);
        if (a->kind == 1) memset(g_coll_value(a, i), 0, a->value_size);
    }
    return found;
}
static void g_coll_clear(g_collection *a) {
    if (a->keys) memset(a->keys, 0, (size_t)a->cap * a->key_size);
    if (a->values) memset(a->values, 0, (size_t)a->cap * a->value_size);
    if (a->states) memset(a->states, 0, (size_t)a->cap);
    a->len = a->used = 0;
}
static g_array g_coll_snapshot(g_collection *a, bool keys, int l, int c) {
    size_t size = keys ? a->key_size : a->value_size;
    g_array out = g_allocate(a->len, size, l, c, keys ? a->key_atomic : a->value_atomic);
    int64_t j = 0;
    for (int64_t i = 0; i < (a->kind == 0 ? a->len : a->cap); ++i)
        if (a->kind == 0 || a->states[i] == 1) {
            memcpy((char *)out.data + (size_t)j++ * size, keys ? g_coll_key(a, i) : g_coll_value(a, i), size);
        }
    return out;
}
static g_collection *g_coll_clone(g_collection *a, int l, int c) {
    g_array keys = {0}, values = {0};
    if (a->kind != 0) keys = g_coll_snapshot(a, true, l, c);
    if (a->kind != 2) values = g_coll_snapshot(a, false, l, c);
    return g_coll_new(a->kind, a->key_kind, a->key_size, a->value_size,
                      a->key_atomic, a->value_atomic, keys, values, l, c);
}
#endif
