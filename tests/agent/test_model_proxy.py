"""Tests for async HTTP server."""

import asyncio
import json
from typing import Any, AsyncGenerator, AsyncIterator

import pytest
from aiohttp import ClientSession
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from test_helpers.utils import skip_if_no_anthropic, skip_if_no_openai

from inspect_ai.agent._bridge.sandbox.proxy import AsyncHTTPServer


@pytest.fixture
async def http_server() -> AsyncGenerator[tuple[AsyncHTTPServer, str], None]:
    """Fixture to create and start an HTTP server for testing."""
    server = AsyncHTTPServer(host="127.0.0.1", port=0)  # port=0 for auto-selection

    async def start_server() -> None:
        # Override the start method to not call serve_forever
        server.server = await asyncio.start_server(
            server._handle_client, server.host, server.port
        )
        # Get the actual port that was assigned
        server.port = server.server.sockets[0].getsockname()[1]

    await start_server()
    base_url = f"http://{server.host}:{server.port}"

    try:
        yield server, base_url
    finally:
        # Clean up
        if server.server:
            server.server.close()
            await server.server.wait_closed()


@pytest.mark.asyncio
async def test_model_proxy_get_request(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test GET request handling."""
    server, base_url = http_server

    # Register a GET handler
    @server.route("/test", method="GET")
    async def test_model_proxy_handler(_request: dict[str, Any]) -> dict[str, Any]:
        return {"status": 200, "body": {"message": "GET successful", "method": "GET"}}

    # Make request
    async with ClientSession() as session:
        async with session.get(f"{base_url}/test") as response:
            assert response.status == 200
            data = await response.json()
            assert data["message"] == "GET successful"
            assert data["method"] == "GET"


@pytest.mark.asyncio
async def test_model_proxy_post_request(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test POST request handling."""
    server, base_url = http_server

    # Register a POST handler
    @server.route("/echo", method="POST")
    async def echo_handler(request: dict[str, Any]) -> dict[str, Any]:
        # New server provides json, text, or raw_body instead of body
        return {"status": 200, "body": {"echo": request.get("json"), "method": "POST"}}

    # Make request
    test_data = {"test": "data", "number": 42}
    async with ClientSession() as session:
        async with session.post(f"{base_url}/echo", json=test_data) as response:
            assert response.status == 200
            data = await response.json()
            assert data["echo"] == test_data
            assert data["method"] == "POST"


@pytest.mark.asyncio
async def test_model_proxy_openai_chat_completions(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI-compatible chat completions endpoint."""
    server, base_url = http_server

    # Register OpenAI chat completions handler
    @server.route("/v1/chat/completions", method="POST")
    async def chat_completions(request: dict[str, Any]) -> dict[str, Any]:
        # New server provides json instead of body
        json_body = request.get("json", {})
        messages = json_body.get("messages", [])
        model = json_body.get("model", "gpt-3.5-turbo")

        # Simple echo response
        response_content = "Test response"
        if messages:
            last_message = messages[-1].get("content", "")
            response_content = f"Echo: {last_message}"

        return {
            "status": 200,
            "body": {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1234567890,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            },
        }

    # Make request
    request_data = {
        "model": "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": "Hello, AI!"}],
    }

    async with ClientSession() as session:
        async with session.post(
            f"{base_url}/v1/chat/completions", json=request_data
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert data["object"] == "chat.completion"
            assert data["model"] == "gpt-3.5-turbo"
            assert len(data["choices"]) == 1
            assert data["choices"][0]["message"]["content"] == "Echo: Hello, AI!"


@pytest.mark.asyncio
async def test_model_proxy_openai_models_list(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI-compatible models list endpoint."""
    server, base_url = http_server

    # Register models list handler
    @server.route("/v1/models", method="GET")
    async def list_models(_request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": 200,
            "body": {
                "object": "list",
                "data": [
                    {
                        "id": "gpt-3.5-turbo",
                        "object": "model",
                        "created": 1677610602,
                        "owned_by": "openai",
                    },
                    {
                        "id": "gpt-4",
                        "object": "model",
                        "created": 1687882411,
                        "owned_by": "openai",
                    },
                ],
            },
        }

    # Make request
    async with ClientSession() as session:
        async with session.get(f"{base_url}/v1/models") as response:
            assert response.status == 200
            data = await response.json()
            assert data["object"] == "list"
            assert len(data["data"]) == 2
            assert data["data"][0]["id"] == "gpt-3.5-turbo"


@pytest.mark.asyncio
async def test_model_proxy_404_not_found(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test 404 response for unregistered paths."""
    _server, base_url = http_server

    async with ClientSession() as session:
        async with session.get(f"{base_url}/nonexistent") as response:
            assert response.status == 404
            data = await response.json()
            assert "error" in data
            assert data["error"]["code"] == 404
            assert data["error"]["type"] == "not_found"


@pytest.mark.asyncio
async def test_model_proxy_add_route_programmatically(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test adding routes programmatically instead of with decorator."""
    server, base_url = http_server

    # Define handler function
    async def custom_handler(_request: dict[str, Any]) -> dict[str, Any]:
        return {"status": 200, "body": {"message": "Programmatically added"}}

    # Add route programmatically
    server.add_route("/custom", custom_handler, method="GET")

    # Make request
    async with ClientSession() as session:
        async with session.get(f"{base_url}/custom") as response:
            assert response.status == 200
            data = await response.json()
            assert data["message"] == "Programmatically added"


@pytest.mark.asyncio
async def test_model_proxy_request_headers_and_body(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test that headers and body are properly parsed and passed to handlers."""
    server, base_url = http_server

    received_request = {}

    @server.route("/inspect", method="POST")
    async def inspect_handler(request: dict[str, Any]) -> dict[str, Any]:
        # Store the request for inspection
        received_request.update(request)
        return {
            "status": 200,
            "body": {
                "headers_received": "content-type" in request.get("headers", {}),
                "body_received": request.get("json") is not None,
            },
        }

    # Make request with custom headers and body
    test_body = {"key": "value", "nested": {"data": 123}}
    async with ClientSession() as session:
        async with session.post(
            f"{base_url}/inspect",
            json=test_body,
            headers={"X-Custom-Header": "test-value"},
        ) as response:
            assert response.status == 200
            data = await response.json()
            assert data["headers_received"] is True
            assert data["body_received"] is True

            # Verify the request was properly parsed
            assert received_request["method"] == "POST"
            assert received_request["path"] == "/inspect"
            assert received_request["json"] == test_body
            assert "content-type" in received_request["headers"]


@pytest.mark.asyncio
async def test_model_proxy_non_json_response(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test returning non-JSON response."""
    server, base_url = http_server

    @server.route("/text", method="GET")
    async def text_handler(_request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": 200,
            "body": "Plain text response",
            "content_type": "text/plain",
        }

    async with ClientSession() as session:
        async with session.get(f"{base_url}/text") as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == "text/plain"
            text = await response.text()
            assert text == "Plain text response"


@pytest.mark.asyncio
async def test_model_proxy_error_handling_in_handler(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test that errors in handlers return 500 status."""
    server, base_url = http_server

    @server.route("/error", method="GET")
    async def error_handler(_request: dict[str, Any]) -> dict[str, Any]:
        raise ValueError("Intentional test error")

    async with ClientSession() as session:
        async with session.get(f"{base_url}/error") as response:
            assert response.status == 500
            data = await response.json()
            assert "error" in data
            assert data["error"]["code"] == 500
            assert "Intentional test error" in data["error"]["message"]


@pytest.mark.asyncio
async def test_model_proxy_multiple_methods_same_path(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test different methods on the same path."""
    server, base_url = http_server

    @server.route("/resource", method="GET")
    async def get_resource(_request: dict[str, Any]) -> dict[str, Any]:
        return {"status": 200, "body": {"method": "GET"}}

    @server.route("/resource", method="POST")
    async def post_resource(_request: dict[str, Any]) -> dict[str, Any]:
        return {"status": 200, "body": {"method": "POST"}}

    async with ClientSession() as session:
        # Test GET
        async with session.get(f"{base_url}/resource") as response:
            assert response.status == 200
            data = await response.json()
            assert data["method"] == "GET"

        # Test POST
        async with session.post(f"{base_url}/resource") as response:
            assert response.status == 200
            data = await response.json()
            assert data["method"] == "POST"


# ============ OpenAI SDK Tests ============


@pytest.mark.asyncio
@skip_if_no_openai
async def test_model_proxy_openai_sdk_models_list(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI SDK models.list() with our server."""
    server, base_url = http_server

    # Register models endpoint
    @server.route("/v1/models", method="GET")
    async def list_models(_request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": 200,
            "body": {
                "object": "list",
                "data": [
                    {
                        "id": "gpt-3.5-turbo",
                        "object": "model",
                        "created": 1677610602,
                        "owned_by": "openai",
                    },
                    {
                        "id": "gpt-4",
                        "object": "model",
                        "created": 1687882411,
                        "owned_by": "openai",
                    },
                ],
            },
        }

    # Use OpenAI SDK
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    models = await client.models.list()
    model_ids = [model.id for model in models.data]
    assert "gpt-3.5-turbo" in model_ids
    assert "gpt-4" in model_ids
    assert len(model_ids) == 2


@pytest.mark.asyncio
@skip_if_no_openai
async def test_model_proxy_openai_sdk_chat_completion(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI SDK chat.completions.create() with our server."""
    server, base_url = http_server

    # Register chat completions endpoint
    @server.route("/v1/chat/completions", method="POST")
    async def chat_completions(request: dict[str, Any]) -> dict[str, Any]:
        json_body = request.get("json", {})
        messages = json_body.get("messages", [])
        model = json_body.get("model", "gpt-3.5-turbo")

        # Echo the last user message
        response_content = "Default response"
        if messages:
            last_message = messages[-1]
            if last_message.get("role") == "user":
                response_content = f"You said: {last_message.get('content', '')}"

        return {
            "status": 200,
            "body": {
                "id": "chatcmpl-test123",
                "object": "chat.completion",
                "created": 1234567890,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": response_content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 15,
                    "total_tokens": 25,
                },
            },
        }

    # Use OpenAI SDK
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    response = await client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, world!"},
        ],
    )

    assert response.choices[0].message.content == "You said: Hello, world!"
    assert response.model == "gpt-3.5-turbo"
    assert response.usage
    assert response.usage.total_tokens == 25


@pytest.mark.asyncio
@skip_if_no_openai
async def test_model_proxy_openai_sdk_streaming(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI SDK streaming response with SSE."""
    server, base_url = http_server

    # SSE generator for streaming response
    async def stream_generator(messages: list[dict[str, Any]]) -> AsyncIterator[bytes]:
        """Generate SSE events for streaming chat completion."""
        # Get the last user message for echo
        content = "Hello"
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    content = msg.get("content", "Hello")
                    break

        # Stream the response word by word
        words = f"You said: {content}".split()

        # Initial message
        yield b'data: {"id":"chatcmpl-stream","object":"chat.completion.chunk","created":1234567890,"model":"gpt-3.5-turbo","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'

        # Stream each word
        for word in words:
            chunk = {
                "id": "chatcmpl-stream",
                "object": "chat.completion.chunk",
                "created": 1234567890,
                "model": "gpt-3.5-turbo",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word + " "},
                        "finish_reason": None,
                    }
                ],
            }
            import json

            yield f"data: {json.dumps(chunk)}\n\n".encode()
            await asyncio.sleep(0.01)  # Small delay to simulate streaming

        # Final message
        yield b'data: {"id":"chatcmpl-stream","object":"chat.completion.chunk","created":1234567890,"model":"gpt-3.5-turbo","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        yield b"data: [DONE]\n\n"

    # Register streaming endpoint
    @server.route("/v1/chat/completions", method="POST")
    async def chat_completions_stream(request: dict[str, Any]) -> dict[str, Any]:
        json_body = request.get("json", {})
        messages = json_body.get("messages", [])
        stream = json_body.get("stream", False)

        if not stream:
            # Non-streaming response
            response_content = "Non-streaming response"
            if messages:
                last_msg = messages[-1]
                if last_msg.get("role") == "user":
                    response_content = f"You said: {last_msg.get('content', '')}"

            return {
                "status": 200,
                "body": {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1234567890,
                    "model": "gpt-3.5-turbo",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": response_content,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 15,
                        "total_tokens": 25,
                    },
                },
            }
        else:
            # Streaming response
            return {
                "status": 200,
                "headers": {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
                "body_iter": stream_generator(messages),
                "chunked": True,
            }

    # Use OpenAI SDK with streaming
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Test streaming response
    stream = await client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": "Hello AI!"}],
        stream=True,
    )

    # Collect streamed chunks
    collected_content = []
    async for chunk in stream:
        if chunk.choices[0].delta.content:
            collected_content.append(chunk.choices[0].delta.content)

    full_response = "".join(collected_content)
    assert "You said: Hello AI!" in full_response


@pytest.mark.asyncio
@skip_if_no_openai
async def test_model_proxy_openai_sdk_error_handling(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI SDK error handling with our server."""
    server, base_url = http_server

    # Register endpoint that returns an error
    @server.route("/v1/chat/completions", method="POST")
    async def chat_completions_error(request: dict[str, Any]) -> dict[str, Any]:
        json_body = request.get("json", {})
        model = json_body.get("model", "")

        if model == "invalid-model":
            return {
                "status": 400,
                "body": {
                    "error": {
                        "message": "Invalid model specified",
                        "type": "invalid_request_error",
                        "code": "model_not_found",
                    }
                },
            }

        return {
            "status": 200,
            "body": {
                "id": "chatcmpl-ok",
                "object": "chat.completion",
                "created": 1234567890,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            },
        }

    # Use OpenAI SDK
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Test successful request
    response = await client.chat.completions.create(
        model="gpt-3.5-turbo", messages=[{"role": "user", "content": "Hi"}]
    )
    assert response.choices[0].message.content == "OK"

    # Test error handling
    from openai import BadRequestError

    with pytest.raises(BadRequestError) as exc_info:
        await client.chat.completions.create(
            model="invalid-model", messages=[{"role": "user", "content": "Hi"}]
        )

    assert "Invalid model specified" in str(exc_info.value)


# ============ Anthropic SDK Tests ============


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_model_proxy_anthropic_sdk_chat_completion(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic SDK messages.create() with our server."""
    server, base_url = http_server

    # Register Anthropic messages endpoint
    @server.route("/v1/messages", method="POST")
    async def messages_handler(request: dict[str, Any]) -> dict[str, Any]:
        json_body = request.get("json", {})
        messages = json_body.get("messages", [])
        model = json_body.get("model", "claude-3-5-sonnet-20241022")

        # Echo the last user message
        response_content = "Default response"
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    # Handle both string and list content formats
                    content = msg.get("content")
                    if isinstance(content, str):
                        response_content = f"You said: {content}"
                    elif isinstance(content, list):
                        # Extract text from content blocks
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        response_content = f"You said: {' '.join(text_parts)}"
                    break

        return {
            "status": 200,
            "body": {
                "id": "msg_test123",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": response_content}],
                "model": model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 15},
            },
        }

    # Use Anthropic SDK (will use API key from env)
    # Note: Anthropic SDK adds /v1 automatically, so we use the base URL directly
    client = AsyncAnthropic(base_url=base_url)

    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello, Claude!"}],
    )

    # Check the response content - only TextBlock has text attribute
    assert len(response.content) > 0
    first_content = response.content[0]
    assert hasattr(first_content, "text")
    assert first_content.text == "You said: Hello, Claude!"
    assert response.model == "claude-3-5-sonnet-20241022"
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 15


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_model_proxy_anthropic_sdk_streaming(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic SDK streaming response."""
    server, base_url = http_server

    # SSE generator for Anthropic streaming
    async def stream_generator(messages: list[dict[str, Any]]) -> AsyncIterator[bytes]:
        """Generate SSE events for Anthropic streaming."""
        # Get the last user message for echo
        content = "Hello"
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "user":
                    msg_content = msg.get("content", "")
                    if isinstance(msg_content, str):
                        content = msg_content
                    elif isinstance(msg_content, list):
                        # Extract text from content blocks
                        text_parts = []
                        for block in msg_content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        content = " ".join(text_parts)
                    break

        # Stream the response word by word
        words = f"You said: {content}".split()

        # Message start event
        start_event = {
            "type": "message_start",
            "message": {
                "id": "msg_stream",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": "claude-3-5-sonnet-20241022",
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0},
            },
        }
        yield f"event: message_start\ndata: {json.dumps(start_event)}\n\n".encode()

        # Content block start
        block_start = {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }
        yield f"event: content_block_start\ndata: {json.dumps(block_start)}\n\n".encode()

        # Stream text deltas
        for word in words:
            delta_event = {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": word + " "},
            }
            yield f"event: content_block_delta\ndata: {json.dumps(delta_event)}\n\n".encode()
            await asyncio.sleep(0.01)  # Small delay to simulate streaming

        # Content block stop
        block_stop = {"type": "content_block_stop", "index": 0}
        yield f"event: content_block_stop\ndata: {json.dumps(block_stop)}\n\n".encode()

        # Message delta with final usage
        delta_event = {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 15},
        }
        yield f"event: message_delta\ndata: {json.dumps(delta_event)}\n\n".encode()

        # Message stop
        stop_event = {"type": "message_stop"}
        yield f"event: message_stop\ndata: {json.dumps(stop_event)}\n\n".encode()

    # Register streaming endpoint
    @server.route("/v1/messages", method="POST")
    async def messages_stream(request: dict[str, Any]) -> dict[str, Any]:
        json_body = request.get("json", {})
        messages = json_body.get("messages", [])
        stream = json_body.get("stream", False)

        if not stream:
            # Non-streaming response
            response_content = "Non-streaming response"
            if messages:
                last_msg = messages[-1]
                if last_msg.get("role") == "user":
                    content = last_msg.get("content", "")
                    if isinstance(content, str):
                        response_content = f"You said: {content}"
                    elif isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text_parts.append(block.get("text", ""))
                        response_content = f"You said: {' '.join(text_parts)}"

            return {
                "status": 200,
                "body": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": response_content}],
                    "model": "claude-3-5-sonnet-20241022",
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 15},
                },
            }
        else:
            # Streaming response
            return {
                "status": 200,
                "headers": {
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
                "body_iter": stream_generator(messages),
                "chunked": True,
            }

    # Use Anthropic SDK with streaming (will use API key from env)
    # Note: Anthropic SDK adds /v1 automatically, so we use the base URL directly
    client = AsyncAnthropic(base_url=base_url)

    # Test streaming response
    stream = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello Claude!"}],
        stream=True,
    )

    # Collect streamed content
    collected_content = []
    async for event in stream:
        if event.type == "content_block_delta":
            if hasattr(event.delta, "text"):
                collected_content.append(event.delta.text)

    full_response = "".join(collected_content)
    assert "You said: Hello Claude!" in full_response


@pytest.mark.asyncio
@skip_if_no_anthropic
async def test_model_proxy_anthropic_sdk_error_handling(
    http_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic SDK error handling with our server."""
    server, base_url = http_server

    # Register endpoint that returns errors
    @server.route("/v1/messages", method="POST")
    async def messages_error(request: dict[str, Any]) -> dict[str, Any]:
        json_body = request.get("json", {})
        model = json_body.get("model", "")

        if model == "invalid-model":
            return {
                "status": 400,
                "body": {
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "message": "Invalid model specified",
                    },
                },
            }

        return {
            "status": 200,
            "body": {
                "id": "msg_ok",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "OK"}],
                "model": model,
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        }

    # Use Anthropic SDK (will use API key from env)
    # Note: Anthropic SDK adds /v1 automatically, so we use the base URL directly
    client = AsyncAnthropic(base_url=base_url)

    # Test successful request
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=100,
        messages=[{"role": "user", "content": "Hi"}],
    )
    # Check the response content - only TextBlock has text attribute
    assert len(response.content) > 0
    first_content = response.content[0]
    assert hasattr(first_content, "text")
    assert first_content.text == "OK"

    # Test error handling
    from anthropic import BadRequestError

    with pytest.raises(BadRequestError) as exc_info:
        await client.messages.create(
            model="invalid-model",
            max_tokens=100,
            messages=[{"role": "user", "content": "Hi"}],
        )

    assert "Invalid model specified" in str(exc_info.value)
