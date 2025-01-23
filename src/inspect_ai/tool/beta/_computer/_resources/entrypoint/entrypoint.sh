#!/bin/bash
set -e

# remove marker files
rm -f /tmp/.X${DISPLAY_NUM}-lock 
rm -f /tmp/xfce_started

/opt/inspect/entrypoint/xvfb_startup.sh
/opt/inspect/entrypoint/xfce_startup.sh
/opt/inspect/entrypoint/x11vnc_startup.sh
/opt/inspect/entrypoint/novnc_startup.sh

# Run CMD if provided
echo "Executing CMD from derived Dockerfile: $@"
exec "$@"

# Keep the container running
tail -f /dev/null
