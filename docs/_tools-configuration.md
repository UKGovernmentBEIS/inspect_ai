

``` dockerfile
RUN python -m venv /opt/inspect_tool_support
ENV PATH="/opt/inspect_tool_support/bin:$PATH"

RUN pip install inspect-tool-support
RUN inspect-tool-support post-install
```

The use of virtual environments is a best practice (and even required in some distributions). The example above creates and activates a `inspect_tool_support` virtual environment before performing the `pip install`.

The `web_browser` tool depends on code in the `inspect-tool-support` package that uses Playwright. Playwright is not supported on some Linux distributions such as `kali`. If you are using such a distribution, you can add the `--no-web-browser` flag to the `post-install` command.

If you don't have a custom Dockerfile, you can alternatively use the pre-built `aisiuk/inspect-tool-support` image:

``` {.yaml filename="compose.yaml"}
services:
  default:
    image: aisiuk/inspect-tool-support:latest
    init: true
```
