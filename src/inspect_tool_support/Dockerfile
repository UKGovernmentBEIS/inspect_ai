# This Dockerfile creates a Docker image that includes inspect-tool-support code.
# This is the container side code implementation for several inspect tools including
# web_browser, bash_session, and text_editor.

FROM python:3.12-bookworm

# if based on an image without Python
# RUN apt-get update && apt-get install -y python3 python3-pip python3-venv

# create and install into a venv
# install inspect-tool-support 
# (on platforms where Playwright is not supported, add --no-web-browser to the post-install command)
ENV PATH="$PATH:/opt/inspect_tool_support/bin"
RUN python -m venv /opt/inspect_tool_support && \
    /opt/inspect_tool_support/bin/pip install inspect-tool-support && \
    /opt/inspect_tool_support/bin/inspect-tool-support post-install

# run forever
CMD ["tail", "-f", "/dev/null"]