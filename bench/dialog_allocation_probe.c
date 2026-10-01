// Bounded successful-call allocation diagnostic against generated application C.
// Map roots intentionally remain reachable; LSan reports lost temporaries.
#define _GNU_SOURCE
#define main dialog_probe_unused_main
#include MADIS_GENERATED_C
#undef main

static MakoCMap *reg, *calls, *cache;
static MakoMutex *lock;
static MakoSqlDB db;
static int proxy_fd, uas_fd, proxy_port, uas_port;
#define V(s) mako_str_view((s), sizeof(s)-1)

static int bind_udp(int *port) {
    int fd = socket(AF_INET, SOCK_DGRAM, 0);
    struct sockaddr_in a = {.sin_family=AF_INET, .sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
    if (fd < 0 || bind(fd, (struct sockaddr*)&a, sizeof(a))) abort();
    socklen_t n=sizeof(a);
    if (getsockname(fd,(struct sockaddr*)&a,&n)) abort();
    *port=ntohs(a.sin_port);
    struct timeval timeout={.tv_sec=2};
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
    return fd;
}

static MakoString process(MakoString msg, int source) {
    return process_sip(msg,msg.len,reg,calls,V("127.0.0.1"),proxy_port,source,
        V("UDP"),proxy_fd,db,0,cache,NULL,V("mako.local"),V("allocation-probe"),lock);
}

static MakoString receive_method(const char *method) {
    char wire[16384];
    ssize_t n=recv(uas_fd,wire,sizeof(wire),0);
    if(n<=0 || (size_t)n<strlen(method) || memcmp(wire,method,strlen(method))) {
        fprintf(stderr,"expected forwarded %s, received %zd bytes\n",method,n); exit(3);
    }
    return mako_str_clone(mako_str_view(wire,(size_t)n));
}

static void require_status(MakoString msg, int expected) {
    int status=(int)mako_sip_status_code(msg);
    if(status!=expected) { fprintf(stderr,"expected %d, got %d\n",expected,status); exit(4); }
    mako_str_free(msg);
}

int main(int argc,char **argv) {
    int count=argc>1?atoi(argv[1]):100;
    if(count<1 || count>100000) return 2;
    setenv("SIP_APP_URL","",1); setenv("SIP_DB_URL","",1);
    setenv("SIP_PUBLIC_IP","127.0.0.1",1);
    setenv("SIP_ALLOW_PRIVATE_TARGETS","1",1);
    setenv("SIP_USER_RATE_LIMIT","1000000",1);
    reg=mako_cmap_new(); calls=mako_cmap_new(); cache=mako_cmap_new(); lock=mako_mutex_new();
    mako_cmap_set(cache,V("_hep_on"),V("0"));
    db=mako_sql_open_postgres(mako_str_empty);
    proxy_fd=bind_udp(&proxy_port); uas_fd=bind_udp(&uas_port);
    char wire[4096],extra[256];
    int n=snprintf(wire,sizeof(wire),"REGISTER sip:mako.local SIP/2.0\r\n"
        "Via: SIP/2.0/UDP 127.0.0.1:15671;branch=z9hG4bK-reg\r\n"
        "From: <sip:bench@mako.local>;tag=reg\r\nTo: <sip:bench@mako.local>\r\n"
        "Call-ID: probe-reg\r\nCSeq: 1 REGISTER\r\n"
        "Contact: <sip:bench@127.0.0.1:%d>\r\nExpires: 3600\r\n"
        "Max-Forwards: 70\r\nContent-Length: 0\r\n\r\n",uas_port);
    require_status(process(mako_str_view(wire,n),15671),200);
    for(int i=0;i<count;i++) {
        n=snprintf(wire,sizeof(wire),"INVITE sip:bench@mako.local SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:15671;branch=z9hG4bK-invite-%d\r\n"
            "From: <sip:caller@mako.local>;tag=caller\r\nTo: <sip:bench@mako.local>\r\n"
            "Call-ID: dialog-probe-%d\r\nCSeq: 1 INVITE\r\n"
            "Contact: <sip:caller@127.0.0.1:15671>\r\n"
            "Max-Forwards: 70\r\nContent-Length: 0\r\n\r\n",i,i);
        require_status(process(mako_str_view(wire,n),15671),100);
        MakoString forwarded=receive_method("INVITE");
        int en=snprintf(extra,sizeof(extra),"Contact: <sip:bench@127.0.0.1:%d>\r\n",uas_port);
        MakoString reply=mako_sip_reply_with_to_tag(forwarded,200,V("OK"),mako_str_view(extra,en),mako_str_empty,V("uas"));
        require_status(process(reply,uas_port),200);
        mako_str_free(reply); mako_str_free(forwarded);
        for(int step=0;step<2;step++) {
            const char *method=step?"BYE":"ACK";
            n=snprintf(wire,sizeof(wire),"%s sip:bench@127.0.0.1:%d SIP/2.0\r\n"
                "Via: SIP/2.0/UDP 127.0.0.1:15671;branch=z9hG4bK-%s-%d\r\n"
                "From: <sip:caller@mako.local>;tag=caller\r\nTo: <sip:bench@mako.local>;tag=uas\r\n"
                "Call-ID: dialog-probe-%d\r\nCSeq: %d %s\r\n"
                "Route: <sip:127.0.0.1:%d;lr>\r\nMax-Forwards: 70\r\nContent-Length: 0\r\n\r\n",
                method,uas_port,method,i,i,step?2:1,method,proxy_port);
            MakoString result=process(mako_str_view(wire,n),15671);
            if(result.len) { fprintf(stderr,"unexpected local %s response\n",method); return 5; }
            mako_str_free(result);
            forwarded=receive_method(method);
            if(step) {
                reply=mako_sip_reply(forwarded,200,V("OK"),mako_str_empty,mako_str_empty);
                require_status(process(reply,uas_port),200);
                mako_str_free(reply);
            }
            mako_str_free(forwarded);
        }
        sip_server_txn_tick(cache,proxy_fd);
        sip_client_txn_tick(cache,proxy_fd,calls,db,0);
    }
    fprintf(stderr,"completed_dialogs=%d calls_entries=%lld cache_entries=%lld\n",count,
        (long long)mako_cmap_len(calls),(long long)mako_cmap_len(cache));
    close(proxy_fd); close(uas_fd);
    return 0;
}
