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

controller = WebBrowserSessionController()


@validated_json_rpc_method(NewSessionParams)
async def web_new_session(params: NewSessionParams) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session(params.headful))


@validated_json_rpc_method(GoParams)
async def web_go(params: GoParams) -> CrawlerResult:
    return await controller.go_to_url(params.session_name, params.url)


@validated_json_rpc_method(ClickParams)
async def web_click(params: ClickParams) -> CrawlerResult:
    return await controller.click(params.session_name, params.element_id)


@validated_json_rpc_method(ScrollParams)
async def web_scroll(params: ScrollParams) -> CrawlerResult:
    return await controller.scroll(params.session_name, params.direction)


@validated_json_rpc_method(CrawlerBaseParams)
async def web_forward(params: CrawlerBaseParams) -> CrawlerResult:
    return await controller.forward(params.session_name)


@validated_json_rpc_method(CrawlerBaseParams)
async def web_back(params: CrawlerBaseParams) -> CrawlerResult:
    return await controller.back(params.session_name)


@validated_json_rpc_method(CrawlerBaseParams)
async def web_refresh(params: CrawlerBaseParams) -> CrawlerResult:
    return await controller.refresh(params.session_name)


@validated_json_rpc_method(TypeOrSubmitParams)
async def web_type(params: TypeOrSubmitParams) -> CrawlerResult:
    return await controller.type_text(
        params.session_name, params.element_id, params.text
    )


@validated_json_rpc_method(TypeOrSubmitParams)
async def web_type_submit(params: TypeOrSubmitParams) -> CrawlerResult:
    return await controller.type_submit(
        params.session_name, params.element_id, params.text
    )
