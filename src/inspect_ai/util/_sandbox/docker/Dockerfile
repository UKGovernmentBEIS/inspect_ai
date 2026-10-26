# Builds the aisiuk/inspect-tool-support image. inspect_ai uses it as the
# default sandbox image when a task has no Dockerfile or compose.yaml, and
# as the container side of the web_browser tool.

FROM python:3.12-bookworm

# Provide an opt-in non-root account (e.g. `user: nonroot` in a compose file).
# UID/GID 65532 follows the distroless "nonroot" convention: it is above
# Debian's useradd auto-assign range (1000-60000), so downstream images'
# auto-assigned users can't land on it, and below nobody (65534) and the
# 16-bit ceiling. The image's default user remains root.
RUN groupadd --gid 65532 nonroot && \
    useradd --create-home --uid 65532 --gid nonroot --shell /bin/bash nonroot

# Install pipx to manage Python applications in isolated environments
RUN apt-get update && apt-get install -y pipx && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install inspect-tool-support to a custom location that's on the path and has permissions granting access to all users
ENV PATH="$PATH:/opt/inspect/bin"
# Install Playwright browsers to a shared location instead of the default
# $HOME/.cache/ms-playwright. post-install runs as root during the build, so
# without this the browsers land under /root and are unresolvable when the
# container runs as nonroot. ENV (not a build ARG) so the same path applies
# both to post-install below and at runtime for every user. The chmod grants
# world read+execute (browser executables need o+rx).
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN PIPX_HOME=/opt/inspect/pipx PIPX_BIN_DIR=/opt/inspect/bin PIPX_VENV_DIR=/opt/inspect/pipx/venvs \
    pipx install inspect-tool-support && \
    chmod -R 755 /opt/inspect && \
    inspect-tool-support post-install && \
    chmod -R a+rX /ms-playwright

CMD ["tail", "-f", "/dev/null"]