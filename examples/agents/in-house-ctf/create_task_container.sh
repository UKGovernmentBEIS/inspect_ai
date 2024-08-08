#!/bin/bash

TASK_NAME=$1
NETWORK_NAME=$2
if [ -z "$TASK_NAME" ] || [ -z "$NETWORK_NAME" ]; then
  echo "Usage: $0 <task_name> <network_name>"
  exit 1
fi

if [ ! -d "challenges/$TASK_NAME" ]; then
  echo "Directory $TASK_NAME does not exist."
  exit 1
fi
cd "challenges/$TASK_NAME"

CONTAINER_NAME="${TASK_NAME}_container"
docker stop $CONTAINER_NAME 2>/dev/null || true
docker rm $CONTAINER_NAME 2>/dev/null || true

IMAGE_NAME="${TASK_NAME}_image"
docker rmi $IMAGE_NAME 2>/dev/null || true

docker build -t $IMAGE_NAME .
if ! docker network ls | grep -q $NETWORK_NAME; then
  docker network create $NETWORK_NAME
fi
docker run -d --name $CONTAINER_NAME --network $NETWORK_NAME $IMAGE_NAME

mkdir -p ../../scratch
CONTAINER_INFO_FILE="../../scratch/${TASK_NAME}_container_info.json"
if [ -f "$CONTAINER_INFO_FILE" ]; then
  rm -f "$CONTAINER_INFO_FILE"
fi
echo '{
    "address": "http://'"${TASK_NAME}"'_container:8080",
    "container_name": "'"${TASK_NAME}"'_container"
}' > $CONTAINER_INFO_FILE

echo "Setup complete. Container ${CONTAINER_NAME} is running on network ${NETWORK_NAME}."