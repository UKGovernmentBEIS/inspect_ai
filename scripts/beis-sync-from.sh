#!/usr/bin/env bash

# created mirror branch with:
# git switch --orphan beis-mirror
# git remote add beis https://github.com/ukgovernmentbeis/inspect_ai.git
# git pull beis main --no-rebase
# git push -u origin beis-mirror
# (then subsequently pointed 'main' at 'beis-mirror')

git pull origin
git pull beis main --no-rebase
git push origin

