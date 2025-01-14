FROM docker.io/ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_PRIORITY=high

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get -y install \
    # UI Requirements
    # A virtual framebuffer for running GUI applications without a physical display.
    xvfb \    
    # A terminal emulator for X.
    xterm \
    # A command-line tool for automating X11 applications (e.g., simulating keyboard/mouse inputs).
    xdotool \
    # A command-line tool for taking screenshots.
    scrot \
    # A suite for image manipulation.
    imagemagick \
    sudo \
    # A lightweight window manager.
    mutter \
    # A VNC server for sharing X11 desktops.
    x11vnc \
    # Python reqs
    python3 \
    python3-pip \
    # Network tools
    # Provides networking tools like ifconfig, netstat, etc.
    net-tools \
    # A versatile networking tool for debugging, port scanning, and more.
    netcat \
    # Adds tools like add-apt-repository for managing PPAs.
    software-properties-common && \
    # Add PPA repository for Firefox
    sudo add-apt-repository ppa:mozillateam/ppa && \
    # Userland apps
    sudo apt-get install -y --no-install-recommends \
    firefox-esr \
    # A lightweight PDF viewer.
    xpdf \
    # A simple text editor.
    gedit \
    # A simple image viewer.
    xpaint \
    # A lightweight taskbar for graphical desktops.
    tint2 \
    # A calculator application.
    galculator \
    # A lightweight file manager.
    pcmanfm && \
    apt-get clean

# setup user
ENV USERNAME=computeruse
ENV HOME=/home/$USERNAME
RUN useradd -m -s /bin/bash -d $HOME $USERNAME
RUN echo "${USERNAME} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
USER computeruse
WORKDIR $HOME

# only reinstall if requirements.txt changes
COPY computer_tool/requirements.txt /opt/computer_tool/requirements.txt
RUN cd /opt/computer_tool && pip3 install --no-cache-dir -r requirements.txt

COPY --chown=$USERNAME:$USERNAME image_home_dir/ $HOME
COPY computer_tool/ /opt/computer_tool
# This is needed if we want to use relative imports in the tool source files.
ENV PYTHONPATH=/opt

EXPOSE 5900
EXPOSE 8080

ARG DISPLAY_NUM=1
ARG HEIGHT=768
ARG WIDTH=1024
ENV DISPLAY_NUM=$DISPLAY_NUM
ENV HEIGHT=$HEIGHT
ENV WIDTH=$WIDTH

ENTRYPOINT [ "./entrypoint.sh" ]
