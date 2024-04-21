import glob
import io
import os
from pathlib import Path
import subprocess
import nbformat

if os.getenv("QUARTO_PROJECT_RENDER_ALL", None) is not None:

    for qmd in glob.glob("_examples/*.qmd"):
        # don't process index.qmd or footer.qmd
        if qmd.endswith("index.qmd") or qmd.endswith("footer.qmd"):
            continue

        # create notebook and compute path to it
        subprocess.run(["quarto", "convert", "--quiet", qmd])
        qmd_name = os.path.splitext(qmd)[0]
        notebook = qmd_name + ".ipynb"

        # read notebook
        with io.open(notebook, "r", encoding="utf-8") as f:
            nb = nbformat.read(f, 4)

        # dest
        stem = Path(qmd_name).stem
        dest = "benchmarks" if stem in ["arc", "gsm8k", "hellaswag", "mathematics"] else "examples"

        # write source
        example = f"../{dest}/{stem}.py"
        with io.open(example, "w", encoding="utf-8") as f:
            for cell in nb.cells:
                if cell.cell_type == "code":
                    source = cell.source
                    # special handling for eval
                    source = source.replace(
                        "eval(", 'if __name__ == "__main__":\n    eval('
                    )
                    f.writelines(source)
                    f.write("\n\n")

        # delete notebook
        Path(notebook).unlink()

    # format examples as required
    subprocess.run(["ruff", "check", "--fix", "../examples", "../benchmarks"])
