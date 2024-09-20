FROM python:3.10-alpine

EXPOSE 1337

RUN apk update; \
    apk add \
      socat;

WORKDIR /usr/src/app

COPY chall/flag.txt .
COPY chall/chall.py .

CMD socat -T 60 \
    TCP-LISTEN:1337,nodelay,reuseaddr,fork \
    EXEC:"python chall.py"
