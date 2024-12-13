#!/usr/bin/env bash

# install commands
HUMAN_AGENT="/opt/human_agent"
mkdir -p $HUMAN_AGENT
cp commands.py $HUMAN_AGENT

# copy documentation
cp welcome.txt ../welcome.txt
cp instructions.txt ../instructions.txt

# create bash aliases for commands
create_alias() {
    echo "alias t$1=\"$HUMAN_AGENT/commands.py $1\"" >> ~/.bashrc
}
for cmd in status start stop submit; do
    create_alias $cmd
done

# add welcome login content
echo 'cat <<- "EOF"' >> ~/.bashrc
cat welcome_login.txt >> ~/.bashrc
echo '' >> ~/.bashrc
echo 'EOF' >> ~/.bashrc




