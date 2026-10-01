// Diagnostic only; production remains Mako. Compile against generated main.c.
// Maps and the lock are intentionally process-lifetime roots. LSan reports
// unreachable request temporaries, not the still-reachable transaction cache.
#define _GNU_SOURCE
#define main allocation_probe_unused_main
#include MADIS_GENERATED_C
#undef main

static MakoCMap *probe_reg, *probe_calls, *probe_cache;
static MakoMutex *probe_lock;
#define VIEW(s) mako_str_view((s), sizeof(s) - 1)

int main(void) {
    setenv("SIP_APP_URL", "", 1);
    setenv("SIP_DB_URL", "", 1);
    setenv("SIP_PUBLIC_IP", "127.0.0.1", 1);
    setenv("SIP_USER_RATE_LIMIT", "1000000", 1);
    probe_reg = mako_cmap_new();
    probe_calls = mako_cmap_new();
    probe_cache = mako_cmap_new();
    probe_lock = mako_mutex_new();
    MakoSqlDB db = mako_sql_open_postgres(mako_str_empty);
    for (int i = 0; i < 100; i++) {
        char wire[1024];
        int n = snprintf(wire, sizeof(wire),
            "INVITE sip:unregistered@example.com SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:15671;branch=z9hG4bK-probe-%d\r\n"
            "From: <sip:a@example.com>;tag=a\r\n"
            "To: <sip:unregistered@example.com>\r\n"
            "Call-ID: allocation-probe-%d\r\nCSeq: 1 INVITE\r\n"
            "Max-Forwards: 70\r\nContent-Length: 0\r\n\r\n", i, i);
        if (n < 0 || (size_t)n >= sizeof(wire)) return 2;
        MakoString msg = mako_str_view(wire, (size_t)n);
        MakoString reply = process_sip_core(msg, n, probe_reg, probe_calls,
            VIEW("127.0.0.1"), 15660, 15671, VIEW("UDP"), -1, db, 0,
            probe_cache, VIEW("example.com"), VIEW("allocation-probe"), probe_lock);
        int64_t status = mako_sip_status_code(reply);
        if (i == 0) fprintf(stderr, "probe_status=%lld\n", (long long)status);
        mako_str_free(reply);
        // This fixture must stop at an unregistered target, without forwarding.
        if (status != 404) return 3;
    }
    return 0;
}
