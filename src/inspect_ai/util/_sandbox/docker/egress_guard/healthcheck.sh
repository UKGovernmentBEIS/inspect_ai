#!/bin/sh
# Healthy only once the deny policy is installed AND both daemons listen. Because the
# entrypoint installs nftables before starting daemons, a passing healthcheck implies
# the fail-closed policy is already active.
set -eu
nft list table inet egress >/dev/null 2>&1
ss -H -lnt 'sport = :3128' | grep -q .
ss -H -lnt 'sport = :3129' | grep -q .
ss -H -lnu 'sport = :53' | grep -q .
