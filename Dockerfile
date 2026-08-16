FROM debian:bookworm-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc make curl ca-certificates libssl-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Mako compiler — adjust this path or mount it at build time
ARG MAKO_BINARY=/usr/local/bin/mako
ARG MAKO_RUNTIME=/usr/local/lib/mako/runtime
COPY . /src
WORKDIR /src

# If the binary is pre-built, just use it. Otherwise emit C and link the
# Mako 0.5.0 output with Madis' small native ownership bridge.
RUN if [ -f /src/main ]; then \
        cp /src/main /src/madis; \
    elif [ -x "$MAKO_BINARY" ]; then \
        rm -f /src/main.c; \
        if ! MAKO_RUNTIME="$MAKO_RUNTIME" "$MAKO_BINARY" build --emit-c --release --strip --no-incremental main.mko -o /tmp/madis-mako > /tmp/mako-build.log 2>&1; then \
            test -s /src/main.c || (cat /tmp/mako-build.log && exit 1); \
        fi; \
        cc -std=c11 -O3 -DNDEBUG -w -I"$MAKO_RUNTIME" -I/usr/include/postgresql \
            -DMAKO_HAS_OPENSSL -DMAKO_USE_OPENSSL -DMAKO_HAS_LIBPQ \
            /src/main.c -o /src/madis \
            -pthread -lm -ldl -lresolv -lssl -lcrypto -lpq; \
    else \
        echo "No pre-built binary and no Mako compiler found." && \
        echo "Either place a compiled 'main' binary in the repo root," && \
        echo "or provide MAKO_BINARY and MAKO_RUNTIME build args." && \
        exit 1; \
    fi

FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates libpq5 libssl3 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --no-create-home --shell /usr/sbin/nologin madis

COPY --from=build /src/madis /usr/local/bin/madis
RUN chmod +x /usr/local/bin/madis

USER madis

EXPOSE 5060/udp 5060/tcp 5061/tcp 8443/tcp 8080/tcp

ENTRYPOINT ["/usr/local/bin/madis"]
