You should add the following to your sandbox `Dockerfile` in order to use this tool:

``` dockerfile
RUN apt-get update && apt-get install -y pipx && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    pipx ensurepath
ENV PATH="$PATH:/root/.local/bin"
RUN pipx install inspect-tool-support && inspect-tool-support post-install
```
