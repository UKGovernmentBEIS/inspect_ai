# Base docker build file.

FROM python:3.12-bookworm

WORKDIR /app/web_browser

RUN apt-get update

RUN pip install --upgrade pip

RUN pip install playwright jsonrpcclient jsonrpcserver httpx aiohttp pillow pydantic tenacity

# Install playwright
RUN playwright install
RUN playwright install-deps 

# Copy Python files alongside the Dockerfile
COPY . .

# Run the server
CMD ["python3", "/app/web_browser/web_server.py"]
# CMD ["tail", "-f", "/dev/null"]