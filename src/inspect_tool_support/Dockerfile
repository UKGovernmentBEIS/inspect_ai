# This Dockerfile creates a Docker image that includes inspect-tool-support code.
# This is the container side code implementation for several inspect tools including
# web_browser, bash_session, and text_editor.

FROM python:3.12-bookworm

# if based on an image without Python
# RUN apt-get update && apt-get install -y python3 python3-pip python3-venv

# create and install into a venv as a best practice
RUN python -m venv /opt/inspect_tool_support
ENV PATH="/opt/inspect_tool_support/bin:$PATH"

# COPY dist/inspect_tool_support-0.1.6.tar.gz /tmp/
# RUN pip install /tmp/inspect_tool_support-0.1.6.tar.gz
RUN pip install inspect-tool-support

# On platforms where Playwright is not supported, add --no-web-browser to the command below
RUN inspect-tool-support post-install


CMD ["tail", "-f", "/dev/null"]