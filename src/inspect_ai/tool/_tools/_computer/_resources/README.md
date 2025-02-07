# About This Image

This image was inspired by Anthropic's Computer Use Demo [here](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo/image).

Its goal is to provide the minimum infrastructure to support the use of Inspect's `computer_tool` to interact with the computer via X11 and `xdotool`, while also providing observability and interaction via VNC and noVNC.

The image extends this minimal functionality by adding a few basic applications — VS Code, Firefox, XPaint, and galculator.

## Entrypoint Directory

1. **Xvfb (X Virtual Framebuffer)**
   - **Script:** `xvfb_startup.sh`
   - **Description:** Xvfb is a display server that implements the X11 display server protocol. It runs in memory and does not require a physical display, useful for running graphical applications in a headless environment.

1. **xfce4**
   - **Script:** `xfce4_startup.sh`
   - **Description:** xfce4 is a lightweight desktop environment for UNIX-like operating systems. It aims to be fast, low on system resources, and user-friendly.

1. **x11vnc**
   - **Script:** `x11vnc_startup.sh`
   - **Description:** x11vnc is a VNC server that allows remote access to the X11 display. It enables users to connect to the virtual display environment from a remote machine using a VNC client.

1. **noVNC**
   - **Script:** `novnc_startup.sh`
   - **Description:** noVNC is a VNC client that runs in a web browser. It allows users to access the virtual display environment through a web interface without needing a separate VNC client application.

## Desktop Directory

The `Desktop` directory contains launchers for VS Code, Firefox and XPaint.

