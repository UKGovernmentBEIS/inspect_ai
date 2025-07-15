v1.1.2 (2025-07-09)

### patch

- Do not start server until it is needed


## v1.1.1 (2025-06-09)

-   Fixed https://github.com/UKGovernmentBEIS/inspect_ai/issues/1964 by including current value in combobox accessibility tree info.

## v1.1.0 (2025-05-02)

### minor

-   Update installation of `inspect-tool-support` in container to use `pipx` instead of `pip`.

### patch

-   Cleaned up code that needlessly created named functions when a lambda would have been sufficient. e.g.

    ```python
    async def go_to_url(self, session_name: str, url: str) -> CrawlerResult:
        async def handler(page: PageCrawler) -> None:
            await page.go_to_url(url)

        return await self._execute_crawler_command(session_name, handler)
    ```

    became

    ```python
    async def go_to_url(self, session_name: str, url: str) -> CrawlerResult:
        return await self._execute_crawler_command(
            session_name, lambda page: page.go_to_url(url)
        )
    ```

## v1.0.1 (29 April 2025)

-   Fix occasional "Execution context was destroyed, most likely because of a navigation" web browser bug. (#1781)

## v1.0.0 (29 April 2025)

-   Major version bump for `bash_session` tool to be terminal oriented rather than command oriented. (#1600)

## v0.1.19 (25 April 2025)

-   Make text editor interface more flexible (#1742)

## v0.1.18 (18 April 2025)

-   Added support for sandboxed Model Context Protocol (MCP) servers.

## v0.1.17 (19 March 2025)

-   Fixed `bash_session` handling of commands whose `stdout` output do not include a trailing newline.
-   Include container side exception details in JSON RPC error response so that they appear in eval logs.
