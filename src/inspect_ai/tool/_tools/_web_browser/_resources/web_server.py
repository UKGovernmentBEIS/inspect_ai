import threading
from typing import Awaitable, Callable, Unpack

from aiohttp.web import Application, Request, Response, run_app
from jsonrpcserver import Result, Success, async_dispatch, method

from constants import DEFAULT_SESSION_NAME, SERVER_PORT
from playwright_browser import PlaywrightBrowser
from playwright_crawler import PlaywrightCrawler
from scale_factor import get_screen_scale_factor
from web_browser_rpc_types import (
    ClickArgs,
    CrawlerBaseArgs,
    CrawlerResponse,
    GoArgs,
    NewSessionArgs,
    NewSessionResponse,
    ScrollArgs,
    TypeOrSubmitArgs,
)


class Sessions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._browser: PlaywrightBrowser | None = None
        self._sessions: dict[str, PlaywrightCrawler] = {}

    async def new_session(self, headful: bool) -> str:
        with self._lock:
            if not self._browser:
                self._browser = await PlaywrightBrowser.create(headless=not headful)
            current_count = len(self._sessions)
            name = (
                DEFAULT_SESSION_NAME
                if current_count == 0
                else f"{DEFAULT_SESSION_NAME}_{current_count}"
            )
            crawler = await PlaywrightCrawler.create(
                await self._browser.get_new_context(),
                device_scale_factor=get_screen_scale_factor() if headful else 1,
            )
            self._sessions[name] = crawler
            return name

    async def get_crawler_for_session(self, name: str) -> PlaywrightCrawler:
        if not self._sessions:
            await self.new_session(False)
        return self._sessions[name]


sessions = Sessions()


@method
async def new_session(**kwargs: Unpack[NewSessionArgs]) -> NewSessionResponse:
    return Success(
        NewSessionResponse(
            session_name=await sessions.new_session(kwargs.get("headful", False))
        ).model_dump()
    )


@method
async def web_go(**kwargs: Unpack[GoArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).go_to_url(kwargs["url"])

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_click(**kwargs: Unpack[ClickArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).click(kwargs["element_id"])

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_scroll(**kwargs: Unpack[ScrollArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).scroll(kwargs["direction"])

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_forward(**kwargs: Unpack[CrawlerBaseArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).forward()

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_back(**kwargs: Unpack[CrawlerBaseArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).back()

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_refresh(**kwargs: Unpack[CrawlerBaseArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).refresh()

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_type(**kwargs: Unpack[TypeOrSubmitArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).type(
            kwargs["element_id"], _str_from_str_or_list(kwargs["text"])
        )

    return await _execute_crawler_command(kwargs["session_name"], handler)


@method
async def web_type_submit(**kwargs: Unpack[TypeOrSubmitArgs]) -> Result:
    async def handler(crawler: PlaywrightCrawler):
        await (await crawler.current_page).clear(kwargs["element_id"])
        await (await crawler.current_page).type(
            kwargs["element_id"], _str_from_str_or_list(kwargs["text"]) + "\n"
        )

    return await _execute_crawler_command(kwargs["session_name"], handler)


async def _execute_crawler_command(
    session_name: str, handler: Callable[[PlaywrightCrawler], Awaitable[None]]
) -> Result:
    if not sessions:
        await new_session()
    try:
        crawler = await sessions.get_crawler_for_session(session_name)
        await handler(crawler)
        await (await crawler.current_page).update()

        # If there's a cookies message click to sort it out.
        await _auto_click_cookies(crawler)

        return Success(
            CrawlerResponse(
                web_url=(await crawler.current_page).url.split("?")[0],
                main_content=(await crawler.current_page).render_main_content(),
                web_at=(await crawler.current_page).render_at(),
                error=None,
            ).model_dump()
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        return Success(
            CrawlerResponse(
                web_url=(await crawler.current_page).url.split("?")[0],
                web_at="encountered error",
                error=str(e),
            ).model_dump()
        )


def _str_from_str_or_list(str_or_list: str | list[str]) -> str:
    return str_or_list if isinstance(str_or_list, str) else " ".join(str_or_list)


async def _auto_click_cookies(crawler: PlaywrightCrawler):
    """Autoclick any cookies popup."""
    try:
        accept_node = (await crawler.current_page).lookup_node("<Accept all>")
    except LookupError:
        return
    await (await crawler.current_page).click(accept_node.node_id)
    await (await crawler.current_page).update()


def main():
    async def handle_request(request: Request) -> Response:
        return Response(
            text=await async_dispatch(await request.text()),
            content_type="application/json",
        )

    app = Application()
    app.router.add_post("/", handle_request)

    run_app(app, port=SERVER_PORT)


if __name__ == "__main__":
    main()
