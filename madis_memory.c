#if defined(__APPLE__) && !defined(_DARWIN_C_SOURCE)
#define _DARWIN_C_SOURCE 1
#endif

#include "mako_rt.h"
#include "mako_cmap.h"
#include "mako_net.h"

/* Forward declare madis_owned_cstr for functions defined before it */
static MakoString madis_owned_cstr(const char *s);

/* ---- Base64url encoding (RFC 4648 §5) ---- */
static size_t madis_b64url_encode(const uint8_t *src, size_t slen, char *dst, size_t dlen) {
    static const char t[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    size_t needed = ((slen + 2) / 3) * 4;
    if (dlen < needed + 1) return 0;
    size_t i = 0, o = 0;
    for (; i + 2 < slen; i += 3) {
        uint32_t v = ((uint32_t)src[i] << 16) | ((uint32_t)src[i+1] << 8) | src[i+2];
        dst[o++] = t[(v >> 18) & 0x3f]; dst[o++] = t[(v >> 12) & 0x3f];
        dst[o++] = t[(v >> 6) & 0x3f]; dst[o++] = t[v & 0x3f];
    }
    if (i < slen) {
        uint32_t v = (uint32_t)src[i] << 16;
        if (i + 1 < slen) v |= (uint32_t)src[i+1] << 8;
        dst[o++] = t[(v >> 18) & 0x3f]; dst[o++] = t[(v >> 12) & 0x3f];
        if (i + 1 < slen) dst[o++] = t[(v >> 6) & 0x3f];
    }
    dst[o] = 0;
    return o;
}

MakoString madis_base64url_encode(MakoString data) {
    if (!data.data || data.len == 0) return madis_owned_cstr("");
    size_t cap = ((data.len + 2) / 3) * 4 + 1;
    char *buf = (char *)malloc(cap);
    if (!buf) return madis_owned_cstr("");
    size_t n = madis_b64url_encode((const uint8_t *)data.data, data.len, buf, cap);
    MakoString result = {buf, n};
    return result;
}

/* ---- STIR/SHAKEN PASSporT JWT signing (RFC 8224/8225) ----
 * Signs a PASSporT with the correct header:
 *   {"alg":"ES256","ppt":"shaken","typ":"passport","x5u":"<cert_url>"}
 * Returns the complete JWT (header.payload.signature) or "" on failure.
 * The runtime's jwt_sign_es256 uses {"alg":"ES256","typ":"JWT"} which
 * does not comply with RFC 8225. */
#ifdef MADIS_TLS_BRIDGE
#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/pem.h>
#include <openssl/ecdsa.h>

MakoString madis_passport_sign(MakoString payload, MakoString private_key_pem, MakoString cert_url) {
    if (!payload.data || payload.len == 0 || payload.len > 8192
        || !private_key_pem.data || private_key_pem.len == 0
        || !cert_url.data || cert_url.len == 0 || cert_url.len > 2048)
        return madis_owned_cstr("");

    /* Build PASSporT header */
    char hdr_json[2200];
    int hdr_n = snprintf(hdr_json, sizeof(hdr_json),
        "{\"alg\":\"ES256\",\"ppt\":\"shaken\",\"typ\":\"passport\",\"x5u\":\"%.*s\"}",
        (int)cert_url.len, cert_url.data);
    if (hdr_n < 0 || (size_t)hdr_n >= sizeof(hdr_json)) return madis_owned_cstr("");

    /* Base64url encode header and payload */
    char hdr_b64[4096], pay_b64[12000];
    size_t hdr_b64_len = madis_b64url_encode((const uint8_t *)hdr_json, (size_t)hdr_n, hdr_b64, sizeof(hdr_b64));
    size_t pay_b64_len = madis_b64url_encode((const uint8_t *)payload.data, payload.len, pay_b64, sizeof(pay_b64));
    if (hdr_b64_len == 0 || pay_b64_len == 0) return madis_owned_cstr("");

    /* Build signing input: header.payload */
    size_t input_len = hdr_b64_len + 1 + pay_b64_len;
    char *input = (char *)malloc(input_len + 1);
    if (!input) return madis_owned_cstr("");
    memcpy(input, hdr_b64, hdr_b64_len);
    input[hdr_b64_len] = '.';
    memcpy(input + hdr_b64_len + 1, pay_b64, pay_b64_len);
    input[input_len] = 0;

    /* Load private key */
    BIO *bio = BIO_new_mem_buf(private_key_pem.data, (int)private_key_pem.len);
    EVP_PKEY *pkey = bio ? PEM_read_bio_PrivateKey(bio, NULL, NULL, NULL) : NULL;
    if (bio) BIO_free(bio);
    if (!pkey) { free(input); return madis_owned_cstr(""); }

    /* Sign with ES256 */
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    size_t der_len = 0;
    unsigned char *der = NULL;
    int ok = ctx && EVP_DigestSignInit(ctx, NULL, EVP_sha256(), NULL, pkey) == 1
        && EVP_DigestSignUpdate(ctx, input, input_len) == 1
        && EVP_DigestSignFinal(ctx, NULL, &der_len) == 1;
    if (ok) {
        if (der_len > 256) ok = 0; /* P-256 DER sig is ~72 bytes max */
        else {
            der = (unsigned char *)malloc(der_len);
            ok = der && EVP_DigestSignFinal(ctx, der, &der_len) == 1;
        }
    }
    if (ctx) EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);

    if (!ok || !der) { free(der); free(input); return madis_owned_cstr(""); }

    /* Convert DER signature to fixed-width R||S (64 bytes for P-256) */
    ECDSA_SIG *sig = NULL;
    const unsigned char *p = der;
    sig = d2i_ECDSA_SIG(NULL, &p, (long)der_len);
    free(der);
    if (!sig) { free(input); return madis_owned_cstr(""); }

    const BIGNUM *r = NULL, *s = NULL;
    ECDSA_SIG_get0(sig, &r, &s);
    unsigned char rs[64];
    memset(rs, 0, 64);
    BN_bn2binpad(r, rs, 32);
    BN_bn2binpad(s, rs + 32, 32);
    ECDSA_SIG_free(sig);

    /* Base64url encode signature */
    char sig_b64[128];
    size_t sig_b64_len = madis_b64url_encode(rs, 64, sig_b64, sizeof(sig_b64));
    if (sig_b64_len == 0) { free(input); return madis_owned_cstr(""); }

    /* Assemble JWT: header.payload.signature */
    size_t total = input_len + 1 + sig_b64_len;
    char *jwt = (char *)malloc(total + 1);
    if (!jwt) { free(input); return madis_owned_cstr(""); }
    memcpy(jwt, input, input_len);
    jwt[input_len] = '.';
    memcpy(jwt + input_len + 1, sig_b64, sig_b64_len);
    jwt[total] = 0;
    free(input);

    return (MakoString){jwt, total};
}
#else
MakoString madis_passport_sign(MakoString payload, MakoString key, MakoString url) {
    (void)payload; (void)key; (void)url; return madis_owned_cstr("");
}
#endif

static int8_t madis_b64url_val(unsigned char c) {
    if (c >= 'A' && c <= 'Z') return (int8_t)(c - 'A');
    if (c >= 'a' && c <= 'z') return (int8_t)(c - 'a' + 26);
    if (c >= '0' && c <= '9') return (int8_t)(c - '0' + 52);
    if (c == '-') return 62;
    if (c == '_') return 63;
    return -1;
}

MakoString madis_base64url_decode(MakoString data) {
    if (!data.data || data.len == 0) return madis_owned_cstr("");
    if (data.len > 65536) return madis_owned_cstr(""); /* cap input size */
    size_t cap = (data.len / 4 + 1) * 3 + 4; /* +4 safety margin for partial blocks */
    uint8_t *buf = (uint8_t *)malloc(cap);
    if (!buf) return madis_owned_cstr("");
    size_t o = 0;
    for (size_t i = 0; i < data.len; ) {
        uint32_t v = 0; int n = 0;
        for (; n < 4 && i < data.len; i++) {
            int8_t c = madis_b64url_val((unsigned char)data.data[i]);
            if (c < 0) continue;
            v = (v << 6) | (uint32_t)c;
            n++;
        }
        if (n >= 2 && o < cap) buf[o++] = (v >> (6*(n-1) - 2)) & 0xff;
        if (n >= 3 && o < cap) buf[o++] = (v >> (6*(n-2) - 4)) & 0xff;
        if (n >= 4 && o < cap) buf[o++] = v & 0xff;
    }
    char *result = (char *)malloc(o + 1);
    if (!result) { free(buf); return madis_owned_cstr(""); }
    memcpy(result, buf, o);
    result[o] = 0;
    free(buf);
    return (MakoString){result, o};
}

/* TLS handle table requires explicit opt-in via -DMADIS_TLS_BRIDGE.
 * The Dockerfile passes this flag; test and CI builds do not. */
#ifdef MADIS_TLS_BRIDGE
#include "mako_http.h"
/* Stub QUIC/HKDF helpers that mako_tls.h compiles unconditionally. */
static inline MakoString mako_sha256_raw(MakoString d) { (void)d; return (MakoString){NULL,0}; }
static inline MakoString mako_hmac_sha256_raw(MakoString k, MakoString d) { (void)k; (void)d; return (MakoString){NULL,0}; }
#include "mako_tls.h"
#endif

#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>


/* Owned string for Mako callers. The runtime's mako_str_from_cstr("") returns
 * a TU-static singleton whose address differs from the runtime TU's empty
 * singleton, so mako_str_free would free a static buffer; always
 * heap-allocate, including the empty string. */
static MakoString madis_owned_cstr(const char *s) {
    if (!s) s = "";
    size_t n = strlen(s);
    char *d = (char *)malloc(n + 1);
    if (!d) {
        fprintf(stderr, "madis: OOM in owned_cstr\n");
        abort();
    }
    memcpy(d, s, n + 1);
    return (MakoString){d, n};
}
int64_t madis_udp_bind_reuseport(int64_t port) {
    if (port <= 0 || port > 65535) return -1;

    mako_sock_t fd = mako_sock_create_af(AF_INET, SOCK_DGRAM);
    if (fd == MAKO_INVALID_SOCK) return -1;

    int yes = 1;
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof(yes));
#if defined(SO_REUSEPORT)
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, (const char *)&yes, sizeof(yes)) != 0) {
        (void)mako_sock_close(fd);
        return -1;
    }
#else
    (void)mako_sock_close(fd);
    return -1;
#endif

    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons((uint16_t)port);
    address.sin_addr.s_addr = htonl(INADDR_ANY);
    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        (void)mako_sock_close(fd);
        return -1;
    }

    mako_sock_set_nonblock(fd, 1);
    return (int64_t)fd;
}

/* SO_REUSEPORT UDP bind on a configured IPv4 literal (SIP_BIND_IP).
 * Returns -1 when the address is not a parseable IPv4 literal. */
int64_t madis_udp_bind_reuseport_addr(MakoString ip, int64_t port) {
    if (port <= 0 || port > 65535) return -1;
    if (!ip.data || ip.len == 0 || ip.len >= 64) return -1;
    char host[64];
    memcpy(host, ip.data, ip.len);
    host[ip.len] = '\0';

    struct sockaddr_in address;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_port = htons((uint16_t)port);
    if (inet_pton(AF_INET, host, &address.sin_addr) != 1) return -1;

    mako_sock_t fd = mako_sock_create_af(AF_INET, SOCK_DGRAM);
    if (fd == MAKO_INVALID_SOCK) return -1;

    int yes = 1;
    (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&yes, sizeof(yes));
#if defined(SO_REUSEPORT)
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, (const char *)&yes, sizeof(yes)) != 0) {
        (void)mako_sock_close(fd);
        return -1;
    }
#else
    (void)mako_sock_close(fd);
    return -1;
#endif

    if (bind(fd, (struct sockaddr *)&address, sizeof(address)) != 0) {
        (void)mako_sock_close(fd);
        return -1;
    }

    mako_sock_set_nonblock(fd, 1);
    return (int64_t)fd;
}

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
    if (!madis_key2(key, sizeof(key), prefix, suffix)) return madis_owned_cstr("");
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
    if (!madis_key3i(key, sizeof(key), prefix, middle, suffix)) return madis_owned_cstr("");
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

/* ---- Server-side TLS connection handle table ----
 * When compiled with -DMADIS_TLS_BRIDGE and the full mako_tls.h available
 * (production Dockerfile), the real implementation is used. Otherwise stubs. */
#ifdef MADIS_TLS_BRIDGE

#define MADIS_TLS_POOL_CAP 8192
static void *madis_tls_table[MADIS_TLS_POOL_CAP];
static int64_t madis_tls_seq = 0;

int64_t madis_tls_srv_accept(void *srv, int64_t fd) {
    void *conn = mako_tls_accept_start(srv, fd);
    if (!conn || mako_tls_conn_fd(conn) < 0) return -1;
    /* Find a free slot. Scan from the sequence counter; if no free slot
     * in a full sweep, reject the connection rather than overwriting an
     * active one (use-after-reassign prevention). */
    int64_t base = __sync_fetch_and_add(&madis_tls_seq, 1);
    for (int scan = 0; scan < MADIS_TLS_POOL_CAP; scan++) {
        int64_t slot = (base + scan) % MADIS_TLS_POOL_CAP;
        if (madis_tls_table[slot] == NULL) {
            madis_tls_table[slot] = conn;
            return slot;
        }
    }
    /* Pool exhausted — close the new connection */
    mako_tls_conn_close(conn);
    return -1;
}

int64_t madis_tls_srv_fd(int64_t handle) {
    if (handle < 0 || handle >= MADIS_TLS_POOL_CAP) return -1;
    void *conn = madis_tls_table[handle];
    if (!conn) return -1;
    return mako_tls_conn_fd(conn);
}

int64_t madis_tls_srv_handshake(int64_t handle) {
    if (handle < 0 || handle >= MADIS_TLS_POOL_CAP) return -1;
    void *conn = madis_tls_table[handle];
    if (!conn) return -1;
    return mako_tls_handshake_step(conn);
}

MakoString madis_tls_srv_read(int64_t handle, int64_t max) {
    if (handle < 0 || handle >= MADIS_TLS_POOL_CAP) return (MakoString){NULL, 0};
    if (max <= 0 || max > 1048576) return (MakoString){NULL, 0};
    void *conn = madis_tls_table[handle];
    if (!conn) return (MakoString){NULL, 0};
    return mako_tls_read_nb(conn, max);
}

int64_t madis_tls_srv_write(int64_t handle, MakoString data) {
    if (handle < 0 || handle >= MADIS_TLS_POOL_CAP) return -1;
    void *conn = madis_tls_table[handle];
    if (!conn) return -1;
    return mako_tls_write_nb(conn, data);
}

int64_t madis_tls_srv_close(int64_t handle) {
    if (handle < 0 || handle >= MADIS_TLS_POOL_CAP) return -1;
    void *conn = madis_tls_table[handle];
    if (!conn) return -1;
    madis_tls_table[handle] = NULL;
    return mako_tls_conn_close(conn);
}

#else /* stubs for test/verify/non-TLS builds */

int64_t madis_tls_srv_accept(void *srv, int64_t fd) { (void)srv; (void)fd; return -1; }
int64_t madis_tls_srv_fd(int64_t handle) { (void)handle; return -1; }
int64_t madis_tls_srv_handshake(int64_t handle) { (void)handle; return -1; }
MakoString madis_tls_srv_read(int64_t handle, int64_t max) { (void)handle; (void)max; return (MakoString){NULL, 0}; }
int64_t madis_tls_srv_write(int64_t handle, MakoString data) { (void)handle; (void)data; return -1; }
int64_t madis_tls_srv_close(int64_t handle) { (void)handle; return -1; }

#endif /* MADIS_TLS_BRIDGE */
