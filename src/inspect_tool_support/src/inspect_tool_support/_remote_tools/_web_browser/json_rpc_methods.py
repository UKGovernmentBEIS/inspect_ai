import os
from pathlib import Path
import sys

from inspect_tool_support._remote_tools._web_browser.controller import (
    WebBrowserSessionController,
)
from inspect_tool_support._remote_tools._web_browser.tool_types import (
    ClickParams,
    CrawlerBaseParams,
    CrawlerResult,
    GoParams,
    NewSessionParams,
    NewSessionResult,
    ScrollParams,
    TypeOrSubmitParams,
)
from inspect_tool_support._util.json_rpc_helpers import validated_json_rpc_method

_controller: WebBrowserSessionController | None = None


def get_controller() -> WebBrowserSessionController:
    global _controller
    if _controller:
        return _controller

    # When running as a PyInstaller onefile binary, all bundled shared libs are extracted
    # under sys._MEIPASS. Ensure the dynamic linker can find them by prepending that
    # lib directory to LD_LIBRARY_PATH before launching Chromium.
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass_lib = Path(getattr(sys, "_MEIPASS")) / "lib"
        existing_ld = os.environ.get("LD_LIBRARY_PATH", "")
        new_ld = f"{meipass_lib}:{existing_ld}" if existing_ld else str(meipass_lib)
        os.environ["LD_LIBRARY_PATH"] = new_ld
        print(f"LD_LIBRARY_PATH set to {os.environ['LD_LIBRARY_PATH']}")
        # Hint Playwright to use packaged browsers and skip host validation inside minimal containers
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
        os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")
        os.environ["DEBUG"] = "pw:api,pw:browser*"


    _controller = WebBrowserSessionController()
    return _controller


@validated_json_rpc_method(NewSessionParams)
async def web_new_session(params: NewSessionParams) -> NewSessionResult:
    controller = get_controller()
    return NewSessionResult(session_name=await controller.new_session(params.headful))


@validated_json_rpc_method(GoParams)
async def web_go(params: GoParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.go_to_url(params.session_name, params.url)


@validated_json_rpc_method(ClickParams)
async def web_click(params: ClickParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.click(params.session_name, params.element_id)


@validated_json_rpc_method(ScrollParams)
async def web_scroll(params: ScrollParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.scroll(params.session_name, params.direction)


@validated_json_rpc_method(CrawlerBaseParams)
async def web_forward(params: CrawlerBaseParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.forward(params.session_name)


@validated_json_rpc_method(CrawlerBaseParams)
async def web_back(params: CrawlerBaseParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.back(params.session_name)


@validated_json_rpc_method(CrawlerBaseParams)
async def web_refresh(params: CrawlerBaseParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.refresh(params.session_name)


@validated_json_rpc_method(TypeOrSubmitParams)
async def web_type(params: TypeOrSubmitParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.type_text(
        params.session_name, params.element_id, params.text
    )


@validated_json_rpc_method(TypeOrSubmitParams)
async def web_type_submit(params: TypeOrSubmitParams) -> CrawlerResult:
    controller = get_controller()
    return await controller.type_submit(
        params.session_name, params.element_id, params.text
    )
