#!/bin/bash

echo "starting XFCE4"
startxfce4 &

while ! pgrep -x "xfce4-session" > /dev/null; do
  echo "Waiting for XFCE4 to start..."
  sleep 1
done

echo "XFCE4 is fully started!"
touch /tmp/xfce_started

