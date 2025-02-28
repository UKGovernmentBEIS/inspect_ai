# Base docker build file.

FROM python:3.12-bookworm

WORKDIR /opt/inspect

RUN pip install --upgrade pip

RUN pip install playwright jsonrpcclient jsonrpcserver httpx aiohttp pillow pydantic tenacity returns

# Install playwright
RUN playwright install
RUN playwright install-deps 

# Copy Python files alongside the Dockerfile
COPY ./container .
COPY ./web_browser_back_compat /app/web_browser
# I wish the COPY above would resolve the symlinks rather than just copying them. 
ADD ./web_browser_back_compat/constants.py /app/web_browser/
ADD ./web_browser_back_compat/tool_types.py /app/web_browser/

# Run the server
CMD ["python3", "/opt/inspect/server.py"]
# CMD ["tail", "-f", "/dev/null"]