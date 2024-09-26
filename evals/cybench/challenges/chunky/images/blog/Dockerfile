FROM ubuntu:20.04

ENV DB="blog.db"
ENV FLAG="SEKAI{tr4nsf3r_3nc0d1ng_ftw!!}"
ENV SECRET_KEY="kgDz@W9ks29myrk8NxiIBqntoZ*N4oBX@"
ENV JWKS_URL_TEMPLATE="http://cache:8080/{user_id}/.well-known/jwks.json"

RUN apt update && apt install -y python3 python3-pip
COPY requirements.txt /tmp
RUN pip install -r /tmp/requirements.txt && rm -f /tmp/requirements.txt

COPY src /app

WORKDIR /app

ENTRYPOINT ["gunicorn", "--access-logfile", "-", "--error-logfile", "-", "-w", "8", "-b", "0.0.0.0:8002", "app:app"]
