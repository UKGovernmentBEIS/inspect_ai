FROM docker.io/ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DEBIAN_PRIORITY=high

# Core/system layer
RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get -y install \
      # A virtual framebuffer for running GUI applications without a physical display.
      xvfb \    
      # A lightweight desktop environment for UNIX-like operating systems.
      xfce4 \
      # The terminal emulator for the xfce4 desktop environment.
      xfce4-terminal\
      # A VNC server for sharing X11 desktops.
      x11vnc \
      # A web based VNC client
      novnc \
      # A WebSocket to TCP proxy/bridge for noVNC
      websockify \
      # The Python programming language interpreter.
      python3 \
      # The package installer for Python.
      python3-pip \
      # A command-line tool for automating X11 applications (e.g., simulating keyboard/mouse inputs).
      xdotool \
      # A command-line tool for taking screenshots.
      scrot \
      # A suite for image manipulation — needed for scaling images.
      imagemagick && \
    apt-get clean

# Userland apt-get'able apps
RUN apt-get install -y --no-install-recommends \
      # A calculator application.
      galculator && \
    apt-get clean

# install Firefox
RUN apt-get install -y software-properties-common && \
    add-apt-repository ppa:mozillateam/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends firefox-esr && \
    apt-get clean

# install VS Code
RUN apt-get install -y \
      gpg \
      wget \
      apt-transport-https \
      software-properties-common && \
    wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > packages.microsoft.gpg && \
    install -D -o root -g root -m 644 packages.microsoft.gpg /etc/apt/keyrings/packages.microsoft.gpg && \
    sh -c 'echo "deb [arch=amd64,arm64 signed-by=/etc/apt/keyrings/packages.microsoft.gpg] https://packages.microsoft.com/repos/code stable main" > /etc/apt/sources.list.d/vscode.list' && \
    apt-get update && \
    apt-get install -y code && \
    apt-get clean

# configure noVNC
RUN ln -s /usr/share/novnc/vnc.html /usr/share/novnc/index.html

# configure python alias
RUN ln -s /usr/bin/python3 /usr/bin/python


# We copy requirements.txt by itself so that changes to the scripts will be in a later layer
# and we only pip install if requirements.txt changes
COPY tool/requirements.txt /opt/inspect/tool/requirements.txt
RUN cd /opt/inspect/tool && pip3 install --no-cache-dir -r requirements.txt

COPY tool/ /opt/inspect/tool
COPY entrypoint/ /opt/inspect/entrypoint
RUN chmod -R 755 /opt/inspect

# setup user
ENV USERNAME=user
ENV HOME=/home/$USERNAME
RUN useradd -m -s /bin/bash -d $HOME $USERNAME
RUN echo "${USERNAME} ALL=(ALL) NOPASSWD: ALL" >> /etc/sudoers
USER ${USERNAME}
WORKDIR $HOME
ADD --chown=$USERNAME:$USERNAME image_home_dir/ $HOME

# configure Firefox to skip all 'first run' UI
RUN mkdir -p $HOME/.mozilla/firefox-esr/profile.default && \
    echo 'user_pref("browser.startup.homepage_override.mstone", "ignore");' >> $HOME/.mozilla/firefox-esr/profile.default/user.js && \
    echo 'user_pref("browser.aboutwelcome.enabled", false);' >> $HOME/.mozilla/firefox-esr/profile.default/user.js && \
    echo 'user_pref("datareporting.policy.firstRunURL", "");' >> $HOME/.mozilla/firefox-esr/profile.default/user.js 
    
EXPOSE 5900
EXPOSE 6080

ARG DISPLAY_NUM=1
ARG WIDTH=1920
ARG HEIGHT=1080
ENV DISPLAY_NUM=$DISPLAY_NUM
ENV DISPLAY=:${DISPLAY_NUM}
ENV HEIGHT=$HEIGHT
ENV WIDTH=$WIDTH

ENTRYPOINT [ "/opt/inspect/entrypoint/entrypoint.sh" ]
