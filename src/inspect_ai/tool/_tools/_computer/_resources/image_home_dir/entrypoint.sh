#!/bin/bash
set -e

export DISPLAY=:${DISPLAY_NUM}
./xvfb_startup.sh
./tint2_startup.sh
./mutter_startup.sh
./x11vnc_startup.sh
./novnc_startup.sh

# Keep the container running
tail -f /dev/null
