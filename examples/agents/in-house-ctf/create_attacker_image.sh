#!/bin/bash

ATTACKER_NAME=$1
if [ -z "$ATTACKER_NAME" ]; then
  echo "Usage: $0 <attacker_name>"
  exit 1
fi

mkdir -p scratch
cd scratch

docker stop $ATTACKER_NAME 2>/dev/null || true
docker rm $ATTACKER_NAME 2>/dev/null || true
docker rmi $ATTACKER_NAME 2>/dev/null || true

DOCKER_FILE="Dockerfile_$ATTACKER_NAME"
cat > $DOCKER_FILE << EOL
FROM ubuntu:20.04
RUN apt-get update && apt-get install -y curl
EOL

docker build -t $ATTACKER_NAME -f $DOCKER_FILE .

rm -f $DOCKER_FILE

echo "Setup complete. Image $ATTACKER_NAME created"