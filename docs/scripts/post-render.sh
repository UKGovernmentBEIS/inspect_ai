#!/bin/bash

files=("index" "tutorial" "options" "log-viewer" "vscode" "tasks" "datasets" "solvers" "tools" "scorers" "models" "providers" "caching" "multimodal" "reasoning" "agents" "sandboxing" "agents-api" "agent-bridge" "human-agent" "approval" "eval-logs" "eval-sets"  "errors-and-limits"  "typing" "tracing" "parallelism" "interactivity" "extensions" "reference/inspect_ai" "reference/inspect_ai.solver" "reference/inspect_ai.tool" "reference/inspect_ai.scorer" "reference/inspect_ai.model" "reference/inspect_ai.dataset" "reference/inspect_ai.approval" "reference/inspect_ai.log" "reference/inspect_ai.util" "reference/inspect_eval" "reference/inspect_eval-set" "reference/inspect_eval-retry" "reference/inspect_score" "reference/inspect_view" "reference/inspect_log" "reference/inspect_trace" "reference/inspect_sandbox" "reference/inspect_cache" "reference/inspect_list" "reference/inspect_info")


if [ "$QUARTO_PROJECT_RENDER_ALL" = "1" ]; then
    llms_full="_site/llms-full.txt"
    rm -f "${llms_full}"
    mv _quarto.yml _quarto.yml.bak
    for file in "${files[@]}"; do
        echo "llms: ${file}.qmd"
        quarto render "${file}.qmd" --to gfm-raw_html --quiet --no-execute
        output_file="${file}.md"
        cat "${output_file}" >> "${llms_full}"
        echo "" >> "${llms_full}"
        mv $output_file "_site/${file}.html.md"
    done
    mv _quarto.yml.bak _quarto.yml
fi




