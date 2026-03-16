"""Path to the sandbox CLI binary injected into sandbox environments.

We choose /var/tmp as the injection location since:
  1) it is accessible in all major linux distributions
  2) all users have permissions to read/write to it (i.e. world-writable)
  3) it is unlikely to be cleared during an evaluation
     (https://en.wikipedia.org/wiki/Filesystem_Hierarchy_Standard)
  4) it is unlikely to be accidentally stumbled upon by an LLM solving a
     task that requires interacting with temp files

We additionally choose a dot-prefixed random hash sub-directory to further
attempt to prevent LLMs from stumbling on the injected tools.
"""

# Also defined in inspect_ai.tool._sandbox_tools_utils._build_config — keep in sync.
SANDBOX_TOOLS_BASE_NAME = "inspect-sandbox-tools"

SANDBOX_CLI = f"/var/tmp/.da7be258e003d428/{SANDBOX_TOOLS_BASE_NAME}"
