# inspect_ai egress-guard runtime image.
# Owns the shared network namespace; enforces NetworkAccess via nftables + dnsmasq + squid.
FROM debian:bookworm-slim

# squid-openssl is Debian's OpenSSL-enabled Squid build. The plain `squid` package
# is built WITHOUT OpenSSL and rejects `ssl-bump` (FATAL: Unknown http_port option).
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      squid-openssl \
      dnsmasq \
      nftables \
      iproute2 \
      openssl \
      procps \
      ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# A single unprivileged identity that dnsmasq and squid drop privileges to. The
# nftables egress-cgroup rule no longer keys on this uid; it is a daemon runtime identity only.
RUN groupadd -g 4242 egress \
 && useradd -u 4242 -g 4242 -M -s /usr/sbin/nologin egress \
 && test "$(id -u egress)" = "4242"

# Self-signed cert to satisfy Squid's ssl-bump port requirement. We only peek+splice
# (never bump/MITM), so this cert is presented ONLY when terminating a denied
# connection; it never signs a forged upstream identity.
RUN install -d -o egress -g egress /etc/squid/ssl_cert \
 && openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
      -keyout /tmp/key.pem -out /tmp/crt.pem -subj "/CN=inspect-egress-guard" \
 && cat /tmp/crt.pem /tmp/key.pem > /etc/squid/ssl_cert/guard.pem \
 && rm -f /tmp/key.pem /tmp/crt.pem \
 && chown egress:egress /etc/squid/ssl_cert/guard.pem \
 && chmod 0400 /etc/squid/ssl_cert/guard.pem

# Runtime dirs owned by the egress uid; config mount point.
RUN install -d -o egress -g egress /var/spool/squid /var/log/squid /run \
 && install -d /etc/egress-guard

COPY entrypoint.sh /usr/local/bin/egress-guard-entrypoint
COPY healthcheck.sh /usr/local/bin/egress-guard-healthcheck
RUN chmod 0755 /usr/local/bin/egress-guard-entrypoint /usr/local/bin/egress-guard-healthcheck

ENTRYPOINT ["/usr/local/bin/egress-guard-entrypoint"]
