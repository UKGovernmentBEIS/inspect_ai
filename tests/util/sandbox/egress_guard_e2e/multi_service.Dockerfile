# Workload whose root supervisor must drop privileges for its HTTP service.
FROM debian:bookworm-slim

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl dnsutils openssl procps python3 supervisor util-linux \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1001 service \
 && useradd --uid 1001 --gid 1001 --create-home --shell /usr/sbin/nologin service \
 && install -d --owner service --group service /srv/internal \
 && printf 'internal egress guard service\n' > /srv/internal/index.html \
 && chown service:service /srv/internal/index.html

COPY multi_service-supervisord.conf /etc/supervisor/conf.d/internal.conf
