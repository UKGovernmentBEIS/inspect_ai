You should add the following to your sandbox `Dockerfile` in order to use this tool:

``` dockerfile
ENV PATH="$PATH:/opt/inspect_tool_support/bin"
RUN python -m venv /opt/inspect_tool_support && \
    /opt/inspect_tool_support/bin/pip install inspect-tool-support && \
    /opt/inspect_tool_support/bin/inspect-tool-support post-install
```
