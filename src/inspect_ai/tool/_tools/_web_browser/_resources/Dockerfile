# This Dockerfile uses a layered approach to switch between headful and headless modes.
# To use the web_browser in headless mode, specify target: headless in your task's docker-compose
# To use the web_browser in headful mode, specify target: headful in your task's docker-compose
# If no target is specified, the default of headless mode is used.

FROM python:3.12-bookworm AS base
WORKDIR /app/web_browser

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

FROM base AS headful
ENV HEADLESS="False"
ENV DISPLAY=:99
EXPOSE 5900

# Install system dependancies for headful browsing
RUN apt-get update \
    && apt-get install -y \
    xvfb \
    x11vnc \
    fluxbox \
    x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

FROM base AS headless
ENV HEADLESS="True"