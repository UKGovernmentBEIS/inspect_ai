# This defines a docker image which the agent can run commands in.
FROM kalilinux/kali-last-release@sha256:92935ba0b1053dc765e627edb65d1981341b662ccaea99271f5ab40e387483a1

# Avoid prompts during package installation.
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y \
    kali-linux-headless \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /root/

# Keep the container running indefinitely.
CMD ["tail", "-f", "/dev/null"]
