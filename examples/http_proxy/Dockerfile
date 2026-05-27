FROM node:20-slim

ENV DEBIAN_FRONTEND=noninteractive

# Python 3 + pip, make `python` point to python3; useful basics
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python-is-python3 \
    git ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally (available to all users)
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# Install mitmproxy
RUN pip install --break-system-packages mitmproxy

# Generate mitmproxy CA certificate at build time so it's ready when
# the container starts. mitmdump generates the cert on first run.
RUN bash -c 'mitmdump > /dev/null 2>&1 & PID=$!; sleep 2; kill $PID 2>/dev/null; exit 0'

# Install the CA cert into the system trust store
RUN cp /root/.mitmproxy/mitmproxy-ca-cert.pem /usr/local/share/ca-certificates/mitmproxy.crt \
    && update-ca-certificates

# Tell Python and Node.js to trust the mitmproxy CA
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV NODE_EXTRA_CA_CERTS=/root/.mitmproxy/mitmproxy-ca-cert.pem

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["tail", "-f", "/dev/null"]
