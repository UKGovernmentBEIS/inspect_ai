#!/bin/bash
set -e

# connection_strategy=lazy defers upstream connections until the request is
# parsed, allowing the addon to remap hosts (like the non-existent
# api.futuremodel.ai) before mitmproxy tries to connect.
mitmdump -s /remap.py --set connection_strategy=lazy -q &

# Wait for mitmproxy to be ready
timeout 30 bash -c 'until echo > /dev/tcp/localhost/8080 2>/dev/null; do sleep 0.5; done'

exec "$@"
