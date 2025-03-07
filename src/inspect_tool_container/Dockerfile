# Base docker build file.

FROM python:3.12-bookworm

WORKDIR /opt/inspect



COPY /inspect_tool_container-0.1.0.tar.gz /tmp/
RUN pip install /tmp/inspect_tool_container-0.1.0.tar.gz

RUN inspect-tool-install

CMD ["tail", "-f", "/dev/null"]