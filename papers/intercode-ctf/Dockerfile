FROM ubuntu:latest

# Install required dependencies
RUN apt-get update && \
    apt-get install -y bash python3 python3-pip psmisc bsdmainutils cron imagemagick dnsutils git wget gcc sleuthkit netcat-traditional unzip curl gdb poppler-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install required pip dependencies
RUN pip3 install pycryptodome cryptography --break-system-packages
