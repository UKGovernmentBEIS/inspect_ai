#!/bin/bash

for file in _site/*.lmd; do
    mv "$file" "${file%.lmd}.md"
done