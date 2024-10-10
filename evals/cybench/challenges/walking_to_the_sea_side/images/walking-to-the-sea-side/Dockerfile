FROM debian:bookworm-slim

EXPOSE 1337

RUN DEBIAN_FRONTEND=noninteractive; \
    apt-get update -y; \
    apt-get install -y \
        socat \
        python3-pip \
    ; \
    apt-get install -y --no-install-recommends sagemath; \
    sage --pip install --break-system-packages pycryptodome

RUN mkdir -p /sage_writable /sage_writable/temp /usr/src/app && \
    chmod 777 /sage_writable /sage_writable/temp /usr/src/app
ENV DOT_SAGE=/sage_writable

WORKDIR /usr/src/app

COPY ./deployment/chal.sage .

RUN sage -preparse chal.sage

ENV USERNAME=default

CMD socat -T 60 \
    TCP4-LISTEN:1337,nodelay,reuseaddr,fork \
    EXEC:"python3 chal.sage.py"
