from jsonrpcserver import method

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
from inspect_tool_support._util._json_rpc_helpers import (
    with_validated_rpc_method_params,
)

controller = WebBrowserSessionController()


@method
async def web_new_session(**params: object) -> object:
    return await with_validated_rpc_method_params(
        NewSessionParams, _web_new_session, **params
    )


@method
async def web_go(**params: object) -> object:
    return await with_validated_rpc_method_params(GoParams, _web_go, **params)


@method
async def web_click(**params: object) -> object:
    return await with_validated_rpc_method_params(ClickParams, _web_click, **params)


@method
async def web_scroll(**params: object) -> object:
    return await with_validated_rpc_method_params(ScrollParams, _web_scroll, **params)


@method
async def web_forward(**params: object) -> object:
    return await with_validated_rpc_method_params(
        CrawlerBaseParams, _web_forward, **params
    )


@method
async def web_back(**params: object) -> object:
    return await with_validated_rpc_method_params(
        CrawlerBaseParams, _web_back, **params
    )


@method
async def web_refresh(**params: object) -> object:
    return await with_validated_rpc_method_params(
        CrawlerBaseParams, _web_refresh, **params
    )


@method
async def web_type(**params: object) -> object:
    return await with_validated_rpc_method_params(
        TypeOrSubmitParams, _web_type, **params
    )


@method
async def web_type_submit(**params: object) -> object:
    return await with_validated_rpc_method_params(
        TypeOrSubmitParams, _web_type_submit, **params
    )


async def _web_new_session(params: NewSessionParams) -> NewSessionResult:
    return NewSessionResult(session_name=await controller.new_session(params.headful))


async def _web_go(params: GoParams) -> CrawlerResult:
    return await controller.go_to_url(params.session_name, params.url)


async def _web_click(params: ClickParams) -> CrawlerResult:
    return await controller.click(params.session_name, params.element_id)


async def _web_scroll(params: ScrollParams) -> CrawlerResult:
    return await controller.scroll(params.session_name, params.direction)


async def _web_forward(params: CrawlerBaseParams) -> CrawlerResult:
    return await controller.forward(params.session_name)


async def _web_back(params: CrawlerBaseParams) -> CrawlerResult:
    return await controller.back(params.session_name)


async def _web_refresh(params: CrawlerBaseParams) -> CrawlerResult:
    return await controller.refresh(params.session_name)


async def _web_type(params: TypeOrSubmitParams) -> CrawlerResult:
    return await controller.type_text(
        params.session_name, params.element_id, params.text
    )


async def _web_type_submit(params: TypeOrSubmitParams) -> CrawlerResult:
    return await controller.type_submit(
        params.session_name, params.element_id, params.text
    )
