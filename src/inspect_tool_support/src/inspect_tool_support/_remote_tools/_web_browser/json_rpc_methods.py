import os
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
    # Detect if running from PyInstaller bundle
    if getattr(sys, "frozen", False):
        # Set LD_LIBRARY_PATH to include the temp directory where staticx extracted files
        mei_pass_dir = sys._MEIPASS
        current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        print(f"\n\n{' '.join(sys.argv)}\n{os.getpid()=}")
        if mei_pass_dir not in current_ld_path.split(":"):
            suffix = f":{current_ld_path}" if current_ld_path else None
            new_path = f"{mei_pass_dir}{suffix}"
            os.environ["LD_LIBRARY_PATH"] = new_path
            print(f"{mei_pass_dir=}\n{current_ld_path=}\n{new_path=}\n\n")
        else:
            print(
                f"LD_LIBRARY_PATH already contained staticx path: {current_ld_path}\n\n"
            )

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
