 #!/usr/bin/env bash

docker stop $(docker ps -a -q)
docker container prune -f
docker image prune -a -f
docker network prune -f 
