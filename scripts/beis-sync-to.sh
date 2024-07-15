#!/usr/bin/env bash

cd ../UKGovernmentBEIS/inspect_ai
git rm -r .
cd ../../inspect_ai
git ls-files > listing.txt

rsync -a . --files-from=listing.txt ../UKGovernmentBEIS/inspect_ai
rm listing.txt

cd ../UKGovernmentBEIS/inspect_ai
rm -rf scripts/beis-sync*.sh
git add --all
cd ../../inspect_ai
