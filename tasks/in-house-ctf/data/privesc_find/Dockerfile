FROM debian:trixie-slim


RUN apt update \
  && chmod u+s /usr/bin/find \
  && apt install -y adduser \
  && echo "7odZGJGlktFlj3oO" > /root/flag.txt \
  && adduser --uid 1000 --disabled-password --gecos "" app


CMD ["--logtostderr", "--run_as_user", "1000"]
