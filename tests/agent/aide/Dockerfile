FROM ubuntu:24.04

RUN apt-get update -y \
    && apt-get upgrade -y \
    && apt-get install -y \
    curl \
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    jq \
    wget \
    make \
    bash \
    git \
    file \
    grep \
    sed \
    gawk \
    coreutils \
    findutils \
    && apt-get clean

# Virtual environment setup
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

RUN pip install --no-cache-dir flake8 ipython pandas genson humanize

# Mock sudo to avoid permission issues
RUN echo -e '#!/bin/sh\nexec "$@"' > /usr/bin/sudo && chmod +x /usr/bin/sudo

# Specify the command to run when the container starts
CMD ["/bin/bash"]

