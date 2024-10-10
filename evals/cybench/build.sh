#!/usr/bin/bash

# Stop if any command fails.
set -e

# Change to the directory of this script so that relative paths resolve relative to this script.
cd "$(dirname "${BASH_SOURCE[0]}")"

# Agent environment.
docker build -t agent-sandbox:1.0.0 ./agent_sandbox/

# Challenge environments.
docker build -t avatar-victim:1.0.0 ./challenges/avatar/images/victim
docker build -t back_to_the_past-victim:1.0.0 ./challenges/back_to_the_past/images/victim
docker build -t chunky-blog:1.0.0 ./challenges/chunky/images/blog
docker build -t chunky-rcache:1.0.0 ./challenges/chunky/images/rcache
docker build -t chunky-nginx:1.0.0 ./challenges/chunky/images/nginx
docker build -t were_pickle_phreaks_revenge-victim:1.0.0 ./challenges/were_pickle_phreaks_revenge/images/victim
docker build -t walking_to_the_sea_side-victim:1.0.0 ./challenges/walking_to_the_sea_side/images/walking-to-the-sea-side
docker build -t unbreakable-victim:1.0.0 ./challenges/unbreakable/images/victim
docker build -t skilift-victim:1.0.0 ./challenges/skilift/images/victim
