#!/bin/bash

files=("index" "tutorial" "workflow" "log-viewer" "vscode" "solvers" "tools" "agents" "agents-api" "scorers" "datasets" "models" "eval-sets" "errors-and-limits" "caching" "parallelism" "interactivity" "approval" "eval-logs" "extensions")


if [ "$QUARTO_PROJECT_RENDER_ALL" = "1" ]; then
    llms_full="_site/llms-full.txt"
    rm -f "${llms_full}"
    mv _quarto.yml _quarto.yml.bak
    for file in "${files[@]}"; do
        echo "llms: ${file}.qmd"
        quarto render "${file}.qmd" --to gfm --quiet --no-execute
        output_file="${file}.md"
        cat "${output_file}" >> "${llms_full}"
        echo "" >> "${llms_full}"
        mv $output_file "_site/${file}.html.md"
    done
    mv _quarto.yml.bak _quarto.yml
fi




