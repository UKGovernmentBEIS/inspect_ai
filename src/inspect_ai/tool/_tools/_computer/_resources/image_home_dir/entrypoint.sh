#!/bin/bash
set -e

export DISPLAY=:${DISPLAY_NUM}

# remove marker files
rm -f /tmp/.X${DISPLAY_NUM}-lock 
rm -f /tmp/mutter_started

./xvfb_startup.sh
./mutter_startup.sh
./tint2_startup.sh
./x11vnc_startup.sh
./novnc_startup.sh

# Keep the container running
tail -f /dev/null
