#ifndef GLYPH_TCP_RUNTIME_H
#define GLYPH_TCP_RUNTIME_H
#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET g_socket;
typedef int g_socklen;
#define G_BAD_SOCKET INVALID_SOCKET
#define g_socket_close closesocket
static bool g_tcp_init(void) { static bool ready; if(!ready) { WSADATA data; if(WSAStartup(MAKEWORD(2,2),&data)) return false; ready=true; } return true; }
static bool g_tcp_nonblock(g_socket s, bool on) { u_long value=on; return !ioctlsocket(s,FIONBIO,&value); }
static bool g_tcp_pending(void) { int e=WSAGetLastError(); return e==WSAEWOULDBLOCK || e==WSAEINPROGRESS; }
#else
#include <sys/socket.h>
#include <sys/time.h>
#include <netdb.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <fcntl.h>
#include <poll.h>
typedef int g_socket;
typedef socklen_t g_socklen;
#define G_BAD_SOCKET (-1)
#define g_socket_close close
static bool g_tcp_init(void) { return true; }
static bool g_tcp_nonblock(g_socket s, bool on) {
    int flags=fcntl(s,F_GETFL,0);
    return flags>=0 && !fcntl(s,F_SETFL,on ? flags|O_NONBLOCK : flags&~O_NONBLOCK);
}
static bool g_tcp_pending(void) { return errno==EINPROGRESS || errno==EWOULDBLOCK; }
#endif
static bool g_tcp_interrupted(void) {
#ifdef _WIN32
    return WSAGetLastError()==WSAEINTR;
#else
    return errno==EINTR;
#endif
}
static bool g_tcp_would_block(void) {
#ifdef _WIN32
    return WSAGetLastError()==WSAEWOULDBLOCK;
#else
    return errno==EAGAIN || errno==EWOULDBLOCK;
#endif
}
/* One monotonic budget survives EINTR and short/nonblocking transfers. */
static int g_tcp_wait_until(g_socket s, bool write, double deadline) {
    for(;;) {
        double remaining=(deadline-g_clock())*1000.0;
        if(remaining<=0) return 0;
        int timeout=remaining>=INT_MAX ? INT_MAX : (int)ceil(remaining);
#ifdef _WIN32
        fd_set set, errors; FD_ZERO(&set); FD_SET(s,&set); FD_ZERO(&errors); FD_SET(s,&errors);
        struct timeval tv={(long)(timeout/1000),(long)(timeout%1000)*1000};
        int r=select(0,write ? NULL : &set,write ? &set : NULL,&errors,&tv);
#else
        struct pollfd p={s,write ? POLLOUT : POLLIN,0};
        int r=poll(&p,1,timeout);
#endif
        if(r>=0 || !g_tcp_interrupted()) return r;
    }
}
static int g_tcp_wait(g_socket s, bool write, int64_t timeout) {
    return g_tcp_wait_until(s,write,g_clock()+(double)timeout/1000.0);
}
static bool g_tcp_config(g_socket s, int64_t timeout) {
#ifdef _WIN32
    DWORD ms=(DWORD)timeout;
    return !setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,(const char*)&ms,sizeof ms) &&
           !setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,(const char*)&ms,sizeof ms) && g_tcp_nonblock(s,true);
#else
    struct timeval tv={(time_t)(timeout/1000),(suseconds_t)(timeout%1000)*1000};
    if(fcntl(s,F_SETFD,FD_CLOEXEC)) return false;
#ifdef SO_NOSIGPIPE
    int yes=1;
    if(setsockopt(s,SOL_SOCKET,SO_NOSIGPIPE,&yes,sizeof yes)) return false;
#endif
    return !setsockopt(s,SOL_SOCKET,SO_RCVTIMEO,&tv,sizeof tv) &&
           !setsockopt(s,SOL_SOCKET,SO_SNDTIMEO,&tv,sizeof tv) && g_tcp_nonblock(s,true);
#endif
}
typedef struct g_tcp_entry { int64_t id, timeout_ms; g_socket socket; bool listener; struct g_tcp_entry *next; } g_tcp_entry;
static g_tcp_entry *g_tcp_handles;
static int64_t g_tcp_serial;
static g_tcp_entry *g_tcp_find(int64_t id) {
    for(g_tcp_entry *e=g_tcp_handles;e;e=e->next) if(e->id==id) return e;
    return NULL;
}
static g_record_IntResult g_tcp_register(g_socket s, bool listener, int64_t timeout, int l, int c) {
    if(g_tcp_serial==INT64_MAX) { g_socket_close(s); return g_error_IntResult("R013","TCP handle IDs exhausted"); }
    g_tcp_entry *e=g_new(1,sizeof(*e),l,c).data;
    e->id=++g_tcp_serial; e->socket=s; e->listener=listener; e->timeout_ms=timeout;
    e->next=g_tcp_handles; g_tcp_handles=e;
    return (g_record_IntResult){true,e->id,{"",0},{"",0}};
}
static g_record_IntResult g_tcp_open(g_str host, int64_t port, int64_t option, bool listener, int l, int c) {
    if(port<0 || port>65535 || (!listener && !port) || option<=0 || option>INT_MAX ||
       (!listener && !host.len) || memchr(host.data,0,(size_t)host.len))
        return g_error_IntResult("R013","invalid TCP host, port, timeout or backlog");
    if(!g_tcp_init()) return g_error_IntResult("R013","cannot initialize sockets");
    char service[8]; snprintf(service,sizeof service,"%d",(int)port);
    struct addrinfo hints={0}, *addresses=NULL;
    hints.ai_family=AF_UNSPEC; hints.ai_socktype=SOCK_STREAM; hints.ai_protocol=IPPROTO_TCP;
    if(listener) hints.ai_flags=AI_PASSIVE;
    if(getaddrinfo(host.len ? g_cstr(host,l,c) : NULL,service,&hints,&addresses))
        return g_error_IntResult("R013","TCP name resolution failed");
    g_socket chosen=G_BAD_SOCKET;
    for(struct addrinfo *a=addresses;a;a=a->ai_next) {
        g_socket s=socket(a->ai_family,a->ai_socktype,a->ai_protocol);
        if(s==G_BAD_SOCKET) continue;
        bool ok=g_tcp_config(s,listener ? 30000 : option);
        if(ok && listener) {
            /* No REUSEADDR on Windows, where it can permit another live listener. */
#ifndef _WIN32
            int yes=1; setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof yes);
#endif
            ok=!bind(s,a->ai_addr,(g_socklen)a->ai_addrlen) && !listen(s,(int)option);
        } else if(ok) {
            ok=g_tcp_nonblock(s,true);
            if(ok && connect(s,a->ai_addr,(g_socklen)a->ai_addrlen)) {
                ok=g_tcp_pending() && g_tcp_wait(s,true,option)>0;
                int error=0; g_socklen size=sizeof error;
                if(ok) ok=!getsockopt(s,SOL_SOCKET,SO_ERROR,(void*)&error,&size) && !error;
            }
        }
        if(ok) { chosen=s; break; }
        g_socket_close(s);
    }
    freeaddrinfo(addresses);
    if(chosen==G_BAD_SOCKET) return g_error_IntResult("R013",listener ? "TCP listen failed" : "TCP connect failed or timed out");
    return g_tcp_register(chosen,listener,listener ? 30000 : option,l,c);
}
static g_record_IntResult g_std_try_tcp_connect(g_str host, int64_t port, int64_t timeout, int l, int c) { return g_tcp_open(host,port,timeout,false,l,c); }
static g_record_IntResult g_std_try_tcp_listen(g_str host, int64_t port, int64_t backlog, int l, int c) { return g_tcp_open(host,port,backlog,true,l,c); }
static g_record_IntResult g_std_try_tcp_accept(int64_t id, int64_t timeout, int l, int c) {
    g_tcp_entry *e=g_tcp_find(id);
    if(!e || !e->listener || timeout<=0 || timeout>INT_MAX) return g_error_IntResult("R013","invalid listener or timeout");
    double deadline=g_clock()+(double)timeout/1000.0;
    for(;;) {
        if(g_tcp_wait_until(e->socket,false,deadline)<=0) return g_error_IntResult("R013","TCP accept failed or timed out");
        g_socket s=accept(e->socket,NULL,NULL);
        if(s==G_BAD_SOCKET) {
            if(g_tcp_interrupted() || g_tcp_would_block()) continue;
            return g_error_IntResult("R013","TCP accept failed");
        }
        if(!g_tcp_config(s,timeout)) { g_socket_close(s); return g_error_IntResult("R013","cannot configure TCP socket"); }
        return g_tcp_register(s,false,timeout,l,c);
    }
}
static g_record_IntResult g_std_try_tcp_port(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_tcp_entry *e=g_tcp_find(id);
    if(!e) return g_error_IntResult("R013","invalid TCP handle");
    struct sockaddr_storage address; g_socklen size=sizeof address;
    if(getsockname(e->socket,(struct sockaddr*)&address,&size)) return g_error_IntResult("R013","cannot read TCP local port");
    int port=address.ss_family==AF_INET ? ntohs(((struct sockaddr_in*)&address)->sin_port) : ntohs(((struct sockaddr_in6*)&address)->sin6_port);
    return (g_record_IntResult){true,port,{"",0},{"",0}};
}
static g_record_BytesResult g_std_try_tcp_read(int64_t id, int64_t count, int l, int c) {
    g_tcp_entry *e=g_tcp_find(id);
    if(!e || e->listener || count<=0 || count>INT_MAX) return g_error_BytesResult("R013","invalid TCP handle or read count");
    char *buffer=g_new_atomic(count,1,l,c).data;
    double deadline=g_clock()+(double)e->timeout_ms/1000.0;
    for(;;) {
        if(g_tcp_wait_until(e->socket,false,deadline)<=0) return g_error_BytesResult("R013","TCP read failed or timed out");
        int64_t n=recv(e->socket,buffer,(int)count,0);
        if(n<0) {
            if(g_tcp_interrupted() || g_tcp_would_block()) continue;
            return g_error_BytesResult("R013","TCP read failed");
        }
        return (g_record_BytesResult){true,g_std_encode_utf8((g_str){buffer,n},l,c),{"",0},{"",0}};
    }
}
static g_record_IntResult g_std_try_tcp_write(int64_t id, g_array bytes, int l, int c) {
    (void)l; (void)c;
    g_tcp_entry *e=g_tcp_find(id);
    if(!e || e->listener) return g_error_IntResult("R013","invalid TCP connection handle");
    if(!g_bytes_valid(bytes)) return g_error_IntResult("R009","byte outside 0..255");
    int64_t used=0; char buffer[8192];
    double deadline=g_clock()+(double)e->timeout_ms/1000.0;
    while(used<bytes.len) {
        int count=(int)((bytes.len-used)>8192 ? 8192 : bytes.len-used);
        for(int i=0;i<count;i++) buffer[i]=(char)((int64_t*)bytes.data)[used+i];
        int flags=0;
#ifdef MSG_NOSIGNAL
        flags=MSG_NOSIGNAL;
#endif
        if(g_tcp_wait_until(e->socket,true,deadline)<=0) return g_error_IntResult("R013","TCP write failed or timed out");
        int64_t n=send(e->socket,buffer,count,flags);
        if(n<0 && (g_tcp_interrupted() || g_tcp_would_block())) continue;
        if(n<=0) return g_error_IntResult("R013","TCP write failed");
        used+=n;
    }
    return (g_record_IntResult){true,used,{"",0},{"",0}};
}
static g_record_BoolResult g_std_try_tcp_close(int64_t id, int l, int c) {
    (void)l; (void)c;
    g_tcp_entry **link=&g_tcp_handles;
    while(*link && (*link)->id!=id) link=&(*link)->next;
    if(!*link) return g_error_BoolResult("R013","invalid or closed TCP handle");
    g_tcp_entry *e=*link; *link=e->next; e->next=NULL;
    if(g_socket_close(e->socket)) return g_error_BoolResult("R013","cannot close TCP socket");
    return (g_record_BoolResult){true,true,{"",0},{"",0}};
}
#endif
