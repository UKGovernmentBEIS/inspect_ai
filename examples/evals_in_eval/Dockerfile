FROM node:20-slim

ENV DEBIAN_FRONTEND=noninteractive

# Python 3 + pip, make `python` point to python3; useful basics
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python-is-python3 \
    git ca-certificates curl procps gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install official Docker CLI (required for nested evals with Docker sandboxes)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin docker-buildx-plugin \
    && rm -rf /var/lib/apt/lists/*

# Install Inspect AI and Anthropic SDK
RUN pip install --no-cache-dir --break-system-packages inspect-ai anthropic

# Install Claude Code globally (available to all users)
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

WORKDIR /workspace

CMD ["/bin/bash"]
