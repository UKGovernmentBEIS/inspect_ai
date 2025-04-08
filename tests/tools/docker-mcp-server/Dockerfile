# base image
FROM python:3.12-bookworm

# nodejs (required by mcp server)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# filesystem mcp server
RUN npm install -g @modelcontextprotocol/server-filesystem

# inspect-tool-support
ENV PATH="$PATH:/opt/inspect_tool_support/bin"
RUN python -m venv /opt/inspect_tool_support && \
    /opt/inspect_tool_support/bin/pip install inspect-tool-support && \
    /opt/inspect_tool_support/bin/inspect-tool-support post-install

# run forever
CMD ["tail", "-f", "/dev/null"]