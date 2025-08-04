You should add the following to your sandbox `Dockerfile` in order to use this tool:

``` dockerfile
RUN apt-get update && apt-get install -y pipx && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
ENV PATH="$PATH:/opt/inspect/bin"
RUN PIPX_HOME=/opt/inspect/pipx PIPX_BIN_DIR=/opt/inspect/bin PIPX_VENV_DIR=/opt/inspect/pipx/venvs \
    pipx install inspect-tool-support && \
    chmod -R 755 /opt/inspect && \
    inspect-tool-support post-install
```
