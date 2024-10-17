#!/bin/bash

chmod +x /root/requirements.sh
./requirements.sh

echo "$(python solve.py HOST=$1 PORT=$2)"

