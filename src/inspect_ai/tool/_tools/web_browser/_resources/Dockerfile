# Base docker build file.

FROM python:3.12-bookworm

WORKDIR /app

RUN apt-get update

RUN pip install --upgrade pip

# Install playwright
RUN pip install playwright 
RUN playwright install
RUN playwright install-deps 

# Install other dependancies
RUN pip install dm-env-rpc pillow bs4 lxml

COPY *.py ./

CMD ["python3", "web_server.py"]