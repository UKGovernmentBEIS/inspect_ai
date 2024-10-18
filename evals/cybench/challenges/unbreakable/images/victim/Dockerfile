FROM python:3.11-slim-buster 

RUN apt update
RUN apt install -y socat

# Add application
WORKDIR /challenge
COPY challenge .

# Expose the port
EXPOSE 1337

# Switch to use a non-root user from here on
USER nobody

# Start the python application
CMD ["socat", "-dd", "TCP-LISTEN:1337,reuseaddr,fork", "exec:python -u /challenge/main.py"]