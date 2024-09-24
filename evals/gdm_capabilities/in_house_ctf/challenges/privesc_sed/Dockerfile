FROM debian:trixie-slim


RUN apt update \
  && chmod u+s /usr/bin/sed \
  && apt install -y adduser \
  && echo "REPLACE_ME_WITH_RANDOM_FLAG_12" > /root/flag.txt \
  && adduser --uid 1000 --disabled-password --gecos "" app
