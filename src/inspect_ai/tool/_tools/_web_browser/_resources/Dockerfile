# Base docker build file.

FROM python:3.12-bookworm

WORKDIR /app/web_browser

RUN apt-get update

RUN pip install --upgrade pip

# Install playwright
RUN pip install playwright 
RUN playwright install
RUN playwright install-deps 

# Install other dependancies
RUN pip install dm-env-rpc pillow bs4 lxml

# Copy Python files alongside the Dockerfile
COPY *.py ./

# Run the server
CMD ["python3", "/app/web_browser/web_server.py"]