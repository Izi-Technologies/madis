#include "mako_rt.h"
#include "mako_cmap.h"

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int madis_key2(char *buf, size_t cap, MakoString prefix, MakoString suffix) {
    if (!buf || cap == 0 || prefix.len > SIZE_MAX - suffix.len) return 0;
    size_t n = prefix.len + suffix.len;
    if (n >= cap) return 0;
    if (prefix.len) memcpy(buf, prefix.data, prefix.len);
    if (suffix.len) memcpy(buf + prefix.len, suffix.data, suffix.len);
    buf[n] = '\0';
    return 1;
}

static int madis_key3i(
    char *buf,
    size_t cap,
    MakoString prefix,
    MakoString middle,
    int64_t suffix
) {
    if (!buf || cap == 0 || prefix.len > SIZE_MAX - middle.len) return 0;
    size_t used = prefix.len + middle.len;
    if (used >= cap) return 0;
    if (prefix.len) memcpy(buf, prefix.data, prefix.len);
    if (middle.len) memcpy(buf + prefix.len, middle.data, middle.len);
    int n = snprintf(buf + used, cap - used, "%lld", (long long)suffix);
    return n >= 0 && (size_t)n < cap - used;
}

static int64_t madis_parse_i64(MakoString value, int64_t fallback) {
    if (!value.data || value.len == 0 || value.len >= 64) return fallback;
    char buf[64];
    memcpy(buf, value.data, value.len);
    buf[value.len] = '\0';
    char *end = NULL;
    errno = 0;
    long long parsed = strtoll(buf, &end, 10);
    if (errno != 0 || end != buf + value.len) return fallback;
    return (int64_t)parsed;
}

int64_t madis_cmap_has2(MakoCMap *cache, MakoString prefix, MakoString suffix) {
    char key[4096];
    if (!madis_key2(key, sizeof(key), prefix, suffix)) return 0;
    return mako_cmap_has(cache, (MakoString){key, strlen(key)});
}

MakoString madis_cmap_get2(MakoCMap *cache, MakoString prefix, MakoString suffix) {
    char key[4096];
    if (!madis_key2(key, sizeof(key), prefix, suffix)) return mako_str_from_cstr("");
    return mako_cmap_get(cache, (MakoString){key, strlen(key)});
}

int64_t madis_cmap_get_i64(MakoCMap *cache, MakoString prefix, MakoString suffix, int64_t fallback) {
    MakoString value = madis_cmap_get2(cache, prefix, suffix);
    int64_t result = madis_parse_i64(value, fallback);
    mako_str_free(value);
    return result;
}

int64_t madis_cmap_has3i(MakoCMap *cache, MakoString prefix, MakoString middle, int64_t suffix) {
    char key[4096];
    if (!madis_key3i(key, sizeof(key), prefix, middle, suffix)) return 0;
    return mako_cmap_has(cache, (MakoString){key, strlen(key)});
}

MakoString madis_cmap_get3i(MakoCMap *cache, MakoString prefix, MakoString middle, int64_t suffix) {
    char key[4096];
    if (!madis_key3i(key, sizeof(key), prefix, middle, suffix)) return mako_str_from_cstr("");
    return mako_cmap_get(cache, (MakoString){key, strlen(key)});
}

int64_t madis_cmap_del3i(MakoCMap *cache, MakoString prefix, MakoString middle, int64_t suffix) {
    char key[4096];
    if (!madis_key3i(key, sizeof(key), prefix, middle, suffix)) return 0;
    return mako_cmap_del(cache, (MakoString){key, strlen(key)});
}

void madis_cmap_set_i64(MakoCMap *cache, MakoString prefix, MakoString suffix, int64_t value) {
    char key[4096];
    if (!madis_key2(key, sizeof(key), prefix, suffix)) return;
    char val[64];
    int n = snprintf(val, sizeof(val), "%lld", (long long)value);
    if (n < 0 || (size_t)n >= sizeof(val)) return;
    mako_cmap_set(cache, (MakoString){key, strlen(key)}, (MakoString){val, (size_t)n});
}
