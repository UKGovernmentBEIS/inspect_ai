# Base docker build file.

FROM python:3.12-bookworm

WORKDIR /app/web_browser

# Install system dependancies (instead of maintaining two images, install headful dependencies
# even though not all dependancies strictly needed in headless mode)
RUN apt-get update \
    && apt-get install -y \
    xvfb \
    x11vnc \
    fluxbox \
    x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

# Install python dependancies
RUN pip install --upgrade pip \
    && pip install playwright dm-env-rpc pillow bs4 lxml

# Install playwright and dependancies
RUN playwright install \
    && playwright install-deps 

# Copy Python files alongside the Dockerfile
COPY *.py ./

# Copy the entrypoint script
COPY entrypoint.sh /app/web_browser/entrypoint.sh
RUN chmod +x /app/web_browser/entrypoint.sh

# Run the entrypoint script at startup
ENTRYPOINT [ "/app/web_browser/entrypoint.sh" ]