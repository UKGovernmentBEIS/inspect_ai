FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive

# Python 3 + pip, make `python` point to python3; Node.js + npm; useful basics
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python-is-python3 \
    nodejs npm \
    git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code globally (available to all users)
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

# Ensure global bin dirs are on PATH for any user
ENV PATH="/usr/local/bin:/usr/bin:${PATH}"

# Default working directory: root's home
WORKDIR /root
RUN chmod 755 /root

CMD ["/bin/bash"]
