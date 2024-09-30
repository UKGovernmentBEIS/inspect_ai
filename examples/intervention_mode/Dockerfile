FROM ubuntu:24.04

# Update the package lists
RUN apt-get update -y && apt-get upgrade -y

# Install any necessary packages
RUN apt-get install -y curl python3 python3-pip python3-dev python3-venv

# Virtual environment setup
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Mock sudo to avoid permission issues
RUN echo -e '#!/bin/sh\nexec "$@"' > /usr/bin/sudo && chmod +x /usr/bin/sudo
# Specify the command to run when the container starts
CMD ["/bin/bash"]
