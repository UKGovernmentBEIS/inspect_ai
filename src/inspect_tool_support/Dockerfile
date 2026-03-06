# This Dockerfile creates a Docker image that includes inspect-tool-support code.
# This is the container side code implementation for several inspect tools including
# web_browser, bash_session, and text_editor.

FROM python:3.12-bookworm

# Install pipx to manage Python applications in isolated environments
RUN apt-get update && apt-get install -y pipx && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install inspect-tool-support to a custom location that's on the path and has permissions granting access to all users
ENV PATH="$PATH:/opt/inspect/bin"
RUN PIPX_HOME=/opt/inspect/pipx PIPX_BIN_DIR=/opt/inspect/bin PIPX_VENV_DIR=/opt/inspect/pipx/venvs \
    pipx install inspect-tool-support && \
    chmod -R 755 /opt/inspect && \
    inspect-tool-support post-install

CMD ["tail", "-f", "/dev/null"]