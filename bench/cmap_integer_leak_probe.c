// Isolate runtime helper ownership; cache stays rooted for LeakSanitizer.
#define _GNU_SOURCE
#include "mako_rt.h"
#include "mako_cmap.h"
#include <assert.h>
static MakoCMap *cache;
int main(void) {
    cache = mako_cmap_new();
    MakoString key = mako_str_view("counter", 7);
    for (int i = 0; i < 1000; i++) {
        mako_cmap_set_int(cache, key, i);
        assert(mako_cmap_get_int(cache, key, -1) == i);
    }
    return 0;
}
