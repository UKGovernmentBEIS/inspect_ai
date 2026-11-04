# Builds the aisiuk/inspect-tool-support image.

FROM python:3.12-bookworm@sha256:a5bab0ff300f91231c2e68bf73a8a8d60762ac39ce1c50eaf6803e4c38a9062b

# Provide an opt-in non-root account (e.g. `user: nonroot` in a compose file).
# UID/GID 65532 follows the distroless "nonroot" convention: it is above
# Debian's useradd auto-assign range (1000-60000), so downstream images'
# auto-assigned users can't land on it, and below nobody (65534) and the
# 16-bit ceiling. The image's default user remains root.
RUN groupadd --gid 65532 nonroot && \
    useradd --create-home --uid 65532 --gid nonroot --shell /bin/bash nonroot

CMD ["tail", "-f", "/dev/null"]
