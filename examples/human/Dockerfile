FROM ubuntu:24.04

# Update the package lists
RUN apt-get update -y && apt-get upgrade -y

# Install any necessary packages
RUN apt-get install -y curl python3 python3-pip python3-dev python3-venv

# Create a non-root user
RUN useradd -m nonroot

# Specify the command to run when the container starts
CMD ["/bin/bash"]
