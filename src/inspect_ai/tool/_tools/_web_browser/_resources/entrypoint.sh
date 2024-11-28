#!/bin/bash
set -e

# If headful mode, spin up Xvfb, Fluxbox and x11vnc for real-time web browser viewing
if [ "$HEADLESS" = "False" ]; then

    # Start Xvfb in the background
    echo "Starting Xvfb..."
    Xvfb :99 -screen 0 1280x1024x24 -ac &

    sleep 2

    # Start Fluxbox in the background
    echo "Starting Fluxbox..."
    fluxbox &

    # Start x11vnc in the background
    echo "Starting VNC server..."
    x11vnc -display :99 -passwd ${VNC_PASSWORD} -forever -shared -verbose &

    # Wait for X server to be ready
    echo "Checking X server with DISPLAY=\${DISPLAY}"
    until xdpyinfo -display :99 >/dev/null 2>&1; do
        echo "Waiting for X server..."
        sleep 1
    done
    echo "X server ready"
fi

# Start the web server (runs in both headless and headful modes)
exec python3 /app/web_browser/web_server.py