# Tiny probe workload: tools are baked before it joins the guarded network namespace.
FROM debian:bookworm-slim
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      curl dnsutils ca-certificates openssl util-linux procps \
 && rm -rf /var/lib/apt/lists/*
