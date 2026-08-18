"""Path to the sandbox tools injected into sandbox environments.

The tools ship as a PyInstaller --onedir bundle (a launcher executable plus an
``_internal`` directory), so what is injected is a directory tree rather than a single
file. ``SANDBOX_TOOLS_DIR`` is where the tree is extracted, and ``SANDBOX_CLI`` is the
launcher inside it.

We choose /var/tmp as the injection location since:
  1) it is accessible in all major linux distributions
  2) all users can create entries there, which supports rootless sandboxes
  3) it is unlikely to be cleared during an evaluation
     (https://en.wikipedia.org/wiki/Filesystem_Hierarchy_Standard)
  4) it is unlikely to be accidentally stumbled upon by an LLM solving a
     task that requires interacting with temp files

We additionally choose a dot-prefixed random hash sub-directory to further
attempt to prevent LLMs from stumbling on the injected tools. When root is
available, the extracted tree is later chmod'ed to 0700 so only the tools user can
access it.
"""

# Also defined in inspect_ai.tool._sandbox_tools_utils._build_config — keep in sync.
SANDBOX_TOOLS_BASE_NAME = "inspect-sandbox-tools"

SANDBOX_TOOLS_DIR = "/var/tmp/.da7be258e003d428"

SANDBOX_CLI = f"{SANDBOX_TOOLS_DIR}/{SANDBOX_TOOLS_BASE_NAME}"
