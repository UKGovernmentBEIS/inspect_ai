FROM python:3.12-bookworm
RUN useradd --create-home --uid 1111 nonroot
# A forged copy of every utility Inspect's own sandbox commands use, in a
# directory the default (non-root) user owns and the image puts first on PATH,
# as images prepared for `pip install --user` commonly do. Each forgery records
# that it ran and fails, so a host command that resolves through the image PATH
# is caught by both the log and its exit status.
RUN mkdir -p /home/nonroot/.local/bin \
    && for name in sh bash rm mkdir tar test stat id chmod tee base64 pwd ls timeout install cat; do \
        printf '#!/bin/sh\necho forged-%s >> /tmp/forged.log\nexit 99\n' "$name" \
            > "/home/nonroot/.local/bin/$name"; \
        chmod 755 "/home/nonroot/.local/bin/$name"; \
    done \
    && chown -R nonroot:nonroot /home/nonroot/.local
ENV PATH=/home/nonroot/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
