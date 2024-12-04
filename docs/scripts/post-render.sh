#!/bin/bash

files=("index" "tutorial" "workflow" "log-viewer" "vscode" "solvers" "tools" "agents" "agents-api" "scorers" "datasets" "models" "eval-sets" "errors-and-limits" "caching" "parallelism" "interactivity" "approval" "eval-logs" "extensions")

llms_full="_site/llms-full.txt"
rm -f "${llms_full}"
for file in "${files[@]}"; do
    path="_site/${file}.html"
    mv "${path}.lmd" "${path}.md"
    cat "${path}.md" >> "${llms_full}"
    echo "" >> "${llms_full}"
done

