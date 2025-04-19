FROM python:3.12-bookworm

RUN useradd -m nonroot

CMD ["tail", "-f", "/dev/null"]
