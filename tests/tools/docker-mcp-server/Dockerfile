# base image
FROM aisiuk/inspect-tool-support

# nodejs (required by mcp server)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# filesystem mcp server
RUN npm install -g @modelcontextprotocol/server-filesystem

# fetch mcp server
RUN pip install mcp_server_fetch