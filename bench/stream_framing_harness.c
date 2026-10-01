// Measurement tooling only; the production application remains pure Mako.
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/resource.h>

static uint64_t framing_allocations, framing_requested_bytes;
static int framing_count_allocations;
static void *framing_malloc(size_t n) {
    if (framing_count_allocations) { framing_allocations++; framing_requested_bytes += n; }
    return malloc(n);
}
static void *framing_calloc(size_t n, size_t size) {
    if (framing_count_allocations) { framing_allocations++; framing_requested_bytes += n * size; }
    return calloc(n, size);
}
static void *framing_realloc(void *p, size_t n) {
    if (framing_count_allocations) { framing_allocations++; framing_requested_bytes += n; }
    return realloc(p, n);
}

#ifdef FRAMING_COUNT_ALLOCATIONS
#define malloc framing_malloc
#define calloc framing_calloc
#define realloc framing_realloc
#endif
#define main framing_unused_main
#include "stream-framing-generated.c"
#undef main
#undef malloc
#undef calloc
#undef realloc

static uint64_t framing_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) { perror("clock_gettime"); exit(1); }
    return (uint64_t)t.tv_sec * 1000000000ULL + t.tv_nsec;
}

int main(int argc, char **argv) {
    if (argc != 5) { fprintf(stderr, "usage: bench variant scenario batches iterations\n"); return 2; }
    int variant = atoi(argv[1]), scenario = atoi(argv[2]);
    int batches = atoi(argv[3]), iterations = atoi(argv[4]);
    if (variant < 0 || variant > 1 || scenario < 0 || scenario > 2 ||
        batches < 1 || batches > 10000 || iterations < 1 || iterations > 1000000) return 2;
    const char *body = "v=0\r\no=alice 1 1 IN IP4 192.0.2.1\r\ns=call\r\nc=IN IP4 192.0.2.1\r\nt=0 0\r\nm=audio 4000 RTP/AVP 0\r\n";
    char text[2048];
    int size = snprintf(text, sizeof(text),
        "INVITE sip:bob@example.com SIP/2.0\r\nVia: SIP/2.0/TCP 192.0.2.1;branch=z9hG4bK-bench\r\n"
        "From: <sip:alice@example.com>;tag=a\r\nTo: <sip:bob@example.com>\r\nCall-ID: framing-bench\r\n"
        "CSeq: 1 INVITE\r\nContent-Type: application/sdp\r\nContent-Length: %zu\r\n\r\n%s", strlen(body), body);
    if (size <= 0 || size >= (int)sizeof(text)) return 2;
    MakoString wire = mako_str_from_cstr(text);
    int64_t expected = scenario == 2 ? 2 * size + size / 3 : size;
    if (framing_bench_run(variant, scenario, 100, wire) != expected * 100) return 3;
    uint64_t *samples = calloc((size_t)batches, sizeof(*samples));
    if (!samples) return 2;
    uint64_t total_ns = 0;
    for (int b = 0; b < batches; b++) {
        framing_count_allocations = 1;
        uint64_t start = framing_ns();
        int64_t checksum = framing_bench_run(variant, scenario, iterations, wire);
        samples[b] = framing_ns() - start;
        framing_count_allocations = 0;
        if (checksum != expected * iterations) { fprintf(stderr, "checksum mismatch\n"); return 3; }
        total_ns += samples[b];
    }
    struct rusage usage;
    if (getrusage(RUSAGE_SELF, &usage) != 0) return 2;
    uint64_t rss_kib = (uint64_t)usage.ru_maxrss;
#ifdef __APPLE__
    rss_kib /= 1024;
#endif
    uint64_t messages = (uint64_t)batches * iterations * (scenario == 2 ? 2 : 1);
    printf("{\"variant\":%d,\"scenario\":%d,\"messages\":%llu,\"total_ns\":%llu,"
           "\"allocations\":%llu,\"requested_bytes\":%llu,\"max_rss_kib\":%llu,\"batch_ns\":[",
           variant, scenario, (unsigned long long)messages, (unsigned long long)total_ns,
           (unsigned long long)framing_allocations, (unsigned long long)framing_requested_bytes,
           (unsigned long long)rss_kib);
    for (int b = 0; b < batches; b++) printf("%s%llu", b ? "," : "", (unsigned long long)samples[b]);
    puts("]}");
    mako_str_free(wire);
    free(samples);
    return 0;
}
