#!/bin/sh
# egress-guard PID 1. Fail-closed ordering:
#   1. install nftables default-deny BEFORE anything can leave and BEFORE health.
#   2. start dnsmasq + squid.
#   3. supervise daemons WITHOUT ever re-touching nftables (no flush-and-gap window).
# If this process dies, the container dies and the shared netns is torn down, so the
# workload loses networking entirely (fail-closed, never open).
set -eu

NFT_CONF=/etc/egress-guard/nftables.conf
DNSMASQ_CONF=/etc/egress-guard/dnsmasq.conf
SQUID_CONF=/etc/egress-guard/squid.conf

# `socket cgroupv2 level 0 "/"` is resolved while nft loads this configuration.
# In Docker's private cgroup namespace, `/` is this guard container's cgroup. Do
# not install the policy if cgroup v2 or that private namespace is unavailable.
if ! test -f /sys/fs/cgroup/cgroup.controllers; then
  echo "egress-guard requires cgroup v2" >&2
  exit 1
fi
if ! grep -qx "0::/" /proc/self/cgroup; then
  echo "egress-guard requires a private cgroup namespace" >&2
  exit 1
fi

# All redirects are OUTPUT-hook (locally generated packets in this guard's own
# netns), so the kernel never treats 127.0.0.1 as martian and no route_localnet
# sysctl is needed.

# Install default-deny before starting either daemon.
nft -f "$NFT_CONF"

start_dnsmasq() {
  dnsmasq --conf-file="$DNSMASQ_CONF" --user=egress --keep-in-foreground &
  DNSMASQ_PID=$!
}
start_squid() {
  squid -f "$SQUID_CONF" -N &
  SQUID_PID=$!
}

start_dnsmasq
start_squid

# 3) supervise. nftables is kernel state and is NOT reloaded here, so a daemon
#    crash/restart cannot open a flush-and-gap window in the deny policy.
trap 'kill "$DNSMASQ_PID" "$SQUID_PID" 2>/dev/null || true; exit 0' TERM INT
while true; do
  kill -0 "$DNSMASQ_PID" 2>/dev/null || start_dnsmasq
  kill -0 "$SQUID_PID" 2>/dev/null || start_squid
  sleep 2
done
