FROM ubuntu:latest

# Install required dependencies
RUN apt-get update && \
    apt-get install -y bash python3 python3-pip psmisc bsdmainutils cron imagemagick tcpdump dnsutils git wget gcc sleuthkit netcat-traditional unzip curl gdb poppler-utils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Alias python to python3
RUN ln -s /usr/bin/python3 /usr/bin/python

# Install required pip dependencies
ENV PIP_BREAK_SYSTEM_PACKAGES 1
RUN pip3 install pyshark scapy pwntools dpkt pycryptodome cryptography owiener numpy sympy requests Pillow python-whois PyPDF2

