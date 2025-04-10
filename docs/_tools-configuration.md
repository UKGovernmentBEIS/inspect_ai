

::: {.callout-note appearance="simple" collapse="true"}
### Sandbox Dependencies

{{< include _sandbox-dockerfile.md >}}

Note that Playwright (used for the `web_browser()` tool) does not support some versions of Linux (e.g. Kali Linux). If this is the case for your Linux distribution, you should add the `--no-web-browser` option to the `post-install`:

```Dockerfile
RUN inspect-tool-support post-install --no-web-browser
```

{{< include _sandbox-image.md >}}

:::

