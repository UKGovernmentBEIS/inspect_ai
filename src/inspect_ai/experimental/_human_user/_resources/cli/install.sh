#!/usr/bin/env bash

# install commands
HUMAN_CLI="/opt/human_cli"
mkdir -p $HUMAN_CLI
cp commands.py $HUMAN_CLI

# create bash aliases for commands
create_alias() {
    echo "alias $1=\"$HUMAN_CLI/commands.py $1\"" >> ~/.bashrc
}
for cmd in start stop note; do
    create_alias $cmd
done




