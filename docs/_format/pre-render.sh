
#!/usr/bin/env bash

if [ -n "${QUARTO_PROJECT_RENDER_ALL}" ]; then
  cd _examples
  cp index.qmd ../examples.qmd
  (echo; echo) >> ../examples.qmd
  for f in security_guide.qmd hellaswag.qmd theory_of_mind.qmd mathematics.qmd biology_qa.qmd arc.qmd tool_use.qmd gsm8k.qmd footer.qmd; do (cat "${f}"; echo; echo; echo) >> ../examples.qmd; done
  cd ..
fi








