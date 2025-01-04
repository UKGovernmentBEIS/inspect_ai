# About This Image

This image is based heavily on the image from Anthropic's Computer Use Demo [here](https://github.com/anthropics/anthropic-quickstarts/tree/main/computer-use-demo/image).

It has been adapted to launch only those tools required for the Inspect `computer_tool` to interact with the computer via X11 and `xdotool`.

## Tools Launched

1. **Xvfb (X Virtual Framebuffer)**
   - **Script:** `xvfb_startup.sh`
   - **Description:** Xvfb is a display server implementing the X11 display server protocol. It runs in memory and does not require a physical display. This is useful for running graphical applications in a headless environment.

2. **tint2**
   - **Script:** `tint2_startup.sh`
   - **Description:** tint2 is a lightweight panel/taskbar. It provides a taskbar, system tray, and application launcher. It is highly configurable and is used to manage and display open applications.

3. **Mutter**
   - **Script:** `mutter_startup.sh`
   - **Description:** Mutter is a window manager for the X Window System. It is used to manage windows and provide compositing effects. In this setup, it is used to replace the default window manager and provide a graphical environment.

4. **x11vnc**
   - **Script:** `x11vnc_startup.sh`
   - **Description:** x11vnc is a VNC server that allows remote access to the X11 display. It enables users to connect to the virtual display environment from a remote machine using a VNC client.

## `.config/tint2` Directory

The `.config/tint2` directory contains configuration files for tint2. These files define the appearance and behavior of the tint2 panel, including the taskbar, system tray, and application launcher. You can customize the tint2 panel by modifying the configuration files in this directory.

