You should add the following to your sandbox `Dockerfile` in order to use this tool:

``` dockerfile
RUN python -m venv /opt/inspect_tool_support
ENV PATH="/opt/inspect_tool_support/bin:$PATH"

RUN pip install inspect-tool-support
RUN inspect-tool-support post-install
```
