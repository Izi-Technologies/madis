// Integer fallback paths must release allocated empty map values too.
#define _GNU_SOURCE
#include "mako_rt.h"
#include "mako_cmap.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static MakoCMap *cache;

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "empty";
    int missing = strcmp(mode, "missing") == 0;
    int composite = strcmp(mode, "composite") == 0;
    if (!missing && !composite && strcmp(mode, "empty") != 0) return 2;
    cache = mako_cmap_new();
    MakoString key = mako_str_view("counter", 7);
    MakoString prefix = mako_str_view("prefix|", 7);
    if (!missing) {
        MakoString stored_key = composite
            ? mako_str_view("prefix|counter", 14) : key;
        mako_cmap_set(cache, stored_key, mako_str_view("", 0));
    }
    for (int i = 0; i < 1000; i++) {
        int64_t value = composite
            ? mako_cmap_get_int2(cache, prefix, key, -17)
            : mako_cmap_get_int(cache, key, -17);
        assert(value == -17);
    }
    fprintf(stderr, "mode=%s iterations=1000 fallback_checks=passed\n", mode);
    return 0;
}
