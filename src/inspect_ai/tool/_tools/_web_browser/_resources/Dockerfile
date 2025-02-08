FROM python:3.12-bookworm
WORKDIR /app/web_browser

# Install python dependancies
RUN pip install --upgrade pip \
    && pip install playwright dm-env-rpc pillow bs4 lxml

# Install playwright and dependancies
RUN playwright install \
    && playwright install-deps

# Install system dependancies for headful browsing
RUN apt-get update \
    && apt-get install -y \
    xvfb \
    x11vnc \
    fluxbox \
    x11-xserver-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy Python files alongside the Dockerfile
COPY *.py ./

# Copy the entrypoint script
COPY entrypoint.sh /app/web_browser/entrypoint.sh
RUN chmod +x /app/web_browser/entrypoint.sh

# Set environment variables (default to headless mode) and expose 5900 by default
ENV HEADLESS="True"
ENV DISPLAY=:99
EXPOSE 5900

# Run the entrypoint script at startup
ENTRYPOINT [ "/app/web_browser/entrypoint.sh" ]
