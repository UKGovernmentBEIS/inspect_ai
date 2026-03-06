"""Tests for async HTTP server."""

import asyncio
import json
from typing import Any, AsyncGenerator, AsyncIterator

import pytest
from aiohttp import ClientSession
from anthropic import AsyncAnthropic
from anthropic.types import ToolParam
from google import genai
from inspect_ai.agent._bridge.sandbox.proxy import AsyncHTTPServer
from openai import AsyncOpenAI
from openai.types.responses import (
    FunctionToolParam,
    ResponseOutputText,
)


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


# ============ OpenAI Responses API Tests ============


@pytest.fixture
async def proxy_server() -> AsyncGenerator[tuple[AsyncHTTPServer, str], None]:
    """Fixture to create and start the actual model proxy server for testing."""
    from inspect_ai.agent._bridge.sandbox.proxy import model_proxy_server

    # Mock the bridge service
    async def mock_bridge_service(
        method: str, json_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Mock implementation of call_bridge_model_service_async."""
        if method == "generate_responses":
            # Return a mock response for testing
            input_data = json_data.get("input", "")

            # Check for special test triggers in input
            if "test_web_search" in str(input_data):
                # Return a ResponseFunctionWebSearch
                return {
                    "id": "resp_web_search",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "web_search_1",
                            "type": "function_call",
                            "call_id": "call_ws123",
                            "name": "web_search",
                            "arguments": '{"query": "latest AI news"}',
                            "status": "completed",
                        }
                    ],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    },
                }
            elif "test_computer" in str(input_data):
                # Return a ResponseComputerToolCall
                return {
                    "id": "resp_computer",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "computer_1",
                            "type": "computer_call",
                            "call_id": "call_comp123",
                            "function": {
                                "name": "computer_tool",
                                "arguments": '{"action": "screenshot"}',
                            },
                            "status": "completed",
                        }
                    ],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    },
                }
            elif "test_reasoning" in str(input_data):
                # Return a ResponseReasoningItem
                return {
                    "id": "resp_reasoning",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "reasoning_1",
                            "type": "reasoning",
                            "content": [
                                {
                                    "type": "reasoning_text",
                                    "text": "Let me think about this step by step...",
                                }
                            ],
                            "summary": [
                                {
                                    "type": "summary_text",
                                    "text": "I analyzed the problem carefully.",
                                }
                            ],
                            "status": "completed",
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 30,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 50,
                    },
                }
            elif "test_mcp_call" in str(input_data):
                # Return an McpCall
                return {
                    "id": "resp_mcp_call",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "mcp_call_1",
                            "type": "mcp_call",
                            "call_id": "call_mcp123",
                            "function": {
                                "name": "mcp_function",
                                "arguments": '{"param": "value"}',
                            },
                            "status": "completed",
                        }
                    ],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "total_tokens": 30,
                    },
                }
            elif "test_mcp_list_tools" in str(input_data):
                # Return an McpListTools
                return {
                    "id": "resp_mcp_list",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "mcp_list_1",
                            "type": "mcp_list_tools",
                            "status": "completed",
                        }
                    ],
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 5,
                        "total_tokens": 25,
                    },
                }

            # Default behavior - check if tool calls are requested
            response_text = (
                f"You said: {input_data}"
                if isinstance(input_data, str)
                else "Test response"
            )
            tools = json_data.get("tools", [])
            if tools:
                # Return a response with tool calls
                return {
                    "id": "resp_tools",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "func_call_1",
                            "type": "function_call",
                            "call_id": "call_abc123",
                            "name": "get_weather",
                            "arguments": '{"location": "San Francisco"}',
                            "status": "completed",
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": tools,
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 10,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 30,
                    },
                }
            else:
                # Return a regular message response
                return {
                    "id": "resp_test123",
                    "object": "response",
                    "created_at": 1234567890,
                    "model": json_data.get("model", "gpt-4o"),
                    "output": [
                        {
                            "id": "msg_test",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": response_text,
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 15,
                        "input_tokens_details": {"cached_tokens": 0},
                        "output_tokens_details": {"reasoning_tokens": 0},
                        "total_tokens": 25,
                    },
                }
        elif method == "generate_completions":
            # Return a mock chat completion for testing
            return {
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1234567890,
                "model": json_data.get("model", "gpt-3.5-turbo"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Test completion response",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 15,
                    "total_tokens": 25,
                },
            }
        else:
            raise ValueError(f"Unknown method: {method}")

    # Create server with mocked bridge service
    server = await model_proxy_server(
        port=0, call_bridge_model_service_async=mock_bridge_service
    )

    # Start server manually (not using start() which blocks)
    server.server = await asyncio.start_server(
        server._handle_client, server.host, server.port
    )

    # Get the actual port that was assigned
    port = server.server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        yield server, base_url
    finally:
        # Clean up
        if server.server:
            server.server.close()
            await server.server.wait_closed()


@pytest.mark.asyncio
async def test_model_proxy_responses_non_streaming(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API non-streaming endpoint using actual OpenAI client."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request using the OpenAI client
    response = await client.responses.create(
        model="gpt-4o",
        input="Hello, Response API!",
    )

    # Verify response
    assert response.object == "response"
    assert response.model == "gpt-4o"
    assert len(response.output) == 1

    # Check the message output
    output_item = response.output[0]
    assert output_item.type == "message"
    assert isinstance(output_item.content[0], ResponseOutputText)
    assert output_item.content[0].text == "You said: Hello, Response API!"


@pytest.mark.asyncio
async def test_model_proxy_responses_streaming(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API streaming endpoint using actual OpenAI client."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Stream response using the OpenAI client
    # Collect events
    events = []
    output_text = ""

    async with client.responses.stream(
        model="gpt-4o",
        input="Hello streaming!",
    ) as stream:
        async for event in stream:
            events.append(event)

            # Collect text from output_text.delta events
            if hasattr(event, "type") and event.type == "response.output_text.delta":
                if hasattr(event, "delta"):
                    output_text += event.delta

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "response.created" in event_types
    assert "response.in_progress" in event_types
    assert "response.output_item.added" in event_types
    assert "response.output_text.delta" in event_types
    assert "response.output_text.done" in event_types
    assert "response.completed" in event_types

    # Verify the streamed text
    assert "You said: Hello streaming!" in output_text


@pytest.mark.asyncio
async def test_model_proxy_responses_with_tool_calls(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API with tool calls using actual OpenAI client."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request with tools
    response = await client.responses.create(
        model="gpt-4o",
        input="What's the weather in San Francisco?",
        tools=[
            FunctionToolParam(
                type="function",
                name="get_weather",
                description="Get the current weather",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                    },
                    "required": ["location"],
                },
                strict=False,
            )
        ],
    )

    # Verify response
    assert response.object == "response"
    assert len(response.output) == 1

    # Check the function call output
    output_item = response.output[0]
    assert output_item.type == "function_call"
    assert output_item.name == "get_weather"
    assert json.loads(output_item.arguments) == {"location": "San Francisco"}


@pytest.mark.asyncio
async def test_model_proxy_responses_streaming_with_tool_calls(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API streaming with tool calls using actual OpenAI client."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Stream response with tools
    # Collect events
    events = []
    function_arguments = ""

    async with client.responses.stream(
        model="gpt-4o",
        input="What's the weather in San Francisco?",
        tools=[
            FunctionToolParam(
                type="function",
                name="get_weather",
                description="Get the current weather",
                parameters={
                    "type": "object",
                    "properties": {
                        "location": {"type": "string"},
                    },
                    "required": ["location"],
                },
                strict=False,
            )
        ],
    ) as stream:
        async for event in stream:
            events.append(event)

            # Collect function arguments from delta events
            if (
                hasattr(event, "type")
                and event.type == "response.function_call_arguments.delta"
            ):
                if hasattr(event, "delta"):
                    function_arguments += event.delta

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "response.created" in event_types
    assert "response.in_progress" in event_types
    assert "response.output_item.added" in event_types
    assert "response.function_call_arguments.delta" in event_types
    assert "response.function_call_arguments.done" in event_types
    assert "response.completed" in event_types

    # Verify the function arguments were streamed correctly
    assert json.loads(function_arguments) == {"location": "San Francisco"}


@pytest.mark.asyncio
async def test_model_proxy_responses_web_search(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API with web_search function call."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request that triggers web search response
    response = await client.responses.create(
        model="gpt-4o",
        input="test_web_search: Find latest AI news",
    )

    # Verify response
    assert response.object == "response"
    assert len(response.output) == 1

    # Check the web search output
    output_item = response.output[0]
    assert output_item.type == "function_call"
    assert output_item.name == "web_search"
    assert json.loads(output_item.arguments) == {"query": "latest AI news"}


@pytest.mark.asyncio
async def test_model_proxy_responses_computer_tool(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API with computer tool call."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request that triggers computer tool response
    response = await client.responses.create(
        model="gpt-4o",
        input="test_computer: Take a screenshot",
    )

    # Verify response
    assert response.object == "response"
    assert len(response.output) == 1

    # Check the computer tool output
    output_item = response.output[0]
    assert output_item.type == "computer_call"
    assert hasattr(output_item, "function")
    # The function field might be a dict
    if isinstance(output_item.function, dict):
        assert output_item.function["name"] == "computer_tool"
        assert json.loads(output_item.function["arguments"]) == {"action": "screenshot"}
    else:
        assert output_item.function.name == "computer_tool"
        assert json.loads(output_item.function.arguments) == {"action": "screenshot"}


@pytest.mark.asyncio
async def test_model_proxy_responses_reasoning(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API with reasoning output."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request that triggers reasoning response
    response = await client.responses.create(
        model="gpt-4o",
        input="test_reasoning: Solve this complex problem",
    )

    # Verify response
    assert response.object == "response"
    assert len(response.output) == 1

    # Check the reasoning output
    output_item = response.output[0]
    assert output_item.type == "reasoning"
    assert hasattr(output_item, "content")
    assert output_item.content is not None
    assert len(output_item.content) > 0
    assert output_item.content[0].type == "reasoning_text"
    assert output_item.content[0].text == "Let me think about this step by step..."

    # Check summary
    assert hasattr(output_item, "summary")
    assert len(output_item.summary) > 0
    assert output_item.summary[0].type == "summary_text"
    assert output_item.summary[0].text == "I analyzed the problem carefully."


@pytest.mark.asyncio
async def test_model_proxy_responses_mcp_call(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API with MCP call."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request that triggers MCP call response
    response = await client.responses.create(
        model="gpt-4o",
        input="test_mcp_call: Execute MCP function",
    )

    # Verify response
    assert response.object == "response"
    assert len(response.output) == 1

    # Check the MCP call output
    output_item = response.output[0]
    assert output_item.type == "mcp_call"
    assert hasattr(output_item, "function")
    # The function field might be a dict
    if isinstance(output_item.function, dict):
        assert output_item.function["name"] == "mcp_function"
        assert json.loads(output_item.function["arguments"]) == {"param": "value"}
    else:
        assert output_item.function.name == "mcp_function"
        assert json.loads(output_item.function.arguments) == {"param": "value"}


@pytest.mark.asyncio
async def test_model_proxy_responses_mcp_list_tools(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API with MCP list tools."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Make request that triggers MCP list tools response
    response = await client.responses.create(
        model="gpt-4o",
        input="test_mcp_list_tools: List available MCP tools",
    )

    # Verify response
    assert response.object == "response"
    assert len(response.output) == 1

    # Check the MCP list tools output
    output_item = response.output[0]
    assert output_item.type == "mcp_list_tools"
    # McpListTools doesn't have a status attribute
    assert hasattr(output_item, "tools")


@pytest.mark.asyncio
async def test_model_proxy_responses_streaming_reasoning(
    proxy_server: tuple[AsyncHTTPServer, str],
) -> None:
    """Test OpenAI Responses API streaming with reasoning output."""
    _server, base_url = proxy_server

    # Use OpenAI client
    client = AsyncOpenAI(base_url=f"{base_url}/v1")

    # Stream response with reasoning
    events = []
    reasoning_text = ""
    summary_text = ""

    try:
        async with client.responses.stream(
            model="gpt-4o",
            input="test_reasoning: Think through this problem",
        ) as stream:
            async for event in stream:
                events.append(event)

                # Collect reasoning text
                if (
                    hasattr(event, "type")
                    and event.type == "response.reasoning_text.delta"
                ):
                    if hasattr(event, "delta"):
                        reasoning_text += event.delta

                # Collect summary text
                if (
                    hasattr(event, "type")
                    and event.type == "response.reasoning_summary_text.delta"
                ):
                    if hasattr(event, "delta"):
                        summary_text += event.delta
    except Exception as e:
        # Print the error for debugging
        print(f"Error during streaming: {e}")
        import traceback

        traceback.print_exc()
        raise

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "response.created" in event_types
    assert "response.in_progress" in event_types
    assert "response.output_item.added" in event_types

    # Check reasoning-specific events
    assert "response.reasoning_text.delta" in event_types
    assert "response.reasoning_text.done" in event_types
    assert "response.reasoning_summary_part.added" in event_types
    assert "response.reasoning_summary_text.delta" in event_types
    assert "response.reasoning_summary_text.done" in event_types
    assert "response.reasoning_summary_part.done" in event_types

    assert "response.completed" in event_types

    # Verify the streamed text
    assert reasoning_text == "Let me think about this step by step..."
    assert summary_text == "I analyzed the problem carefully."


# ============ Anthropic Messages API Tests ============


@pytest.fixture
async def proxy_server_anthropic() -> AsyncGenerator[tuple[AsyncHTTPServer, str], None]:
    """Fixture to create and start the model proxy server for Anthropic testing."""
    from inspect_ai.agent._bridge.sandbox.proxy import model_proxy_server

    # Mock the bridge service for Anthropic
    async def mock_bridge_service_anthropic(
        method: str, json_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Mock implementation of call_bridge_model_service_async for Anthropic."""
        if method == "generate_anthropic":
            # Get the messages from the request
            messages = json_data.get("messages", [])
            tools = json_data.get("tools", [])

            # Check for special test triggers
            last_message_content = ""
            if messages:
                last_msg = messages[-1]
                if isinstance(last_msg.get("content"), str):
                    last_message_content = last_msg.get("content", "")
                elif isinstance(last_msg.get("content"), list):
                    # Handle content array format
                    for content in last_msg.get("content", []):
                        if content.get("type") == "text":
                            last_message_content = content.get("text", "")
                            break

            # Generate different responses based on content
            if "test_web_search" in last_message_content:
                # Return a web search tool use response
                return {
                    "id": "msg_web_search_test",
                    "type": "message",
                    "role": "assistant",
                    "model": json_data.get("model", "claude-opus-4-1-20250805"),
                    "content": [
                        {
                            "type": "text",
                            "text": "I'll search the web for that information.",
                        },
                        {
                            "type": "server_tool_use",
                            "id": "srvtoolu_test123",
                            "name": "web_search",
                            "input": {"query": "latest AI news"},
                        },
                    ],
                    "stop_reason": "tool_use",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 25,
                        "output_tokens": 20,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
            elif "test_mcp" in last_message_content:
                # Return an MCP tool use response
                return {
                    "id": "msg_mcp_test",
                    "type": "message",
                    "role": "assistant",
                    "model": json_data.get("model", "claude-opus-4-1-20250805"),
                    "content": [
                        {"type": "text", "text": "I'll use the MCP tool for that."},
                        {
                            "type": "tool_use",
                            "id": "toolu_mcp123",
                            "name": "mcp_function",
                            "input": {"param": "value"},
                        },
                    ],
                    "stop_reason": "tool_use",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 15,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
            elif "test_thinking" in last_message_content:
                # Return a thinking response
                return {
                    "id": "msg_thinking_test",
                    "type": "message",
                    "role": "assistant",
                    "model": json_data.get("model", "claude-opus-4-1-20250805"),
                    "content": [
                        {
                            "type": "thinking",
                            "thinking": "Let me work through this problem step by step.",
                            "signature": "EqQBCgIYAhIM1gbcDa9GJwZA2b3hGgxBdjrkzLoky3dl1pkiMOYds",
                        },
                        {
                            "type": "text",
                            "text": "Based on my analysis, the answer is 42.",
                        },
                    ],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 20,
                        "output_tokens": 50,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
            elif tools and "weather" in last_message_content.lower():
                # Return a tool use response
                return {
                    "id": "msg_tool_test",
                    "type": "message",
                    "role": "assistant",
                    "model": json_data.get("model", "claude-opus-4-1-20250805"),
                    "content": [
                        {"type": "text", "text": "I'll check the weather for you."},
                        {
                            "type": "tool_use",
                            "id": "toolu_test123",
                            "name": "get_weather",
                            "input": {"location": "San Francisco, CA"},
                        },
                    ],
                    "stop_reason": "tool_use",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 30,
                        "output_tokens": 25,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
            else:
                # Default text response
                response_text = (
                    f"You said: {last_message_content}"
                    if last_message_content
                    else "Hello! How can I help you today?"
                )
                return {
                    "id": "msg_test123",
                    "type": "message",
                    "role": "assistant",
                    "model": json_data.get("model", "claude-opus-4-1-20250805"),
                    "content": [{"type": "text", "text": response_text}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 10,
                        "output_tokens": 15,
                        "cache_creation_input_tokens": 0,
                        "cache_read_input_tokens": 0,
                    },
                }
        else:
            raise ValueError(f"Unknown method: {method}")

    # Create server with mocked bridge service
    server = await model_proxy_server(
        port=0,
        call_bridge_model_service_async=mock_bridge_service_anthropic,
    )

    # Start server manually (not using start() which blocks)
    server.server = await asyncio.start_server(
        server._handle_client, server.host, server.port
    )

    # Get the actual port that was assigned
    port = server.server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        yield server, base_url
    finally:
        # Clean up
        if server.server:
            server.server.close()
            await server.server.wait_closed()


@pytest.mark.asyncio
async def test_anthropic_messages_non_streaming(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API non-streaming endpoint."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Make request
    response = await client.messages.create(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "Hello, Claude!"}],
        max_tokens=256,
    )

    # Verify response
    assert response.type == "message"
    assert response.role == "assistant"
    assert len(response.content) == 1
    assert response.content[0].type == "text"
    assert response.content[0].text == "You said: Hello, Claude!"
    assert response.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_anthropic_messages_streaming(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API streaming endpoint."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Stream response
    collected_text = ""
    events = []

    async with client.messages.stream(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "Hello streaming!"}],
        max_tokens=256,
    ) as stream:
        async for event in stream:
            events.append(event)

            # Manually collect text from events
            if hasattr(event, "type"):
                if event.type == "content_block_delta":
                    if hasattr(event, "delta") and hasattr(event.delta, "text"):
                        collected_text += event.delta.text

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "message_start" in event_types
    assert "content_block_start" in event_types
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types
    assert "message_delta" in event_types
    assert "message_stop" in event_types

    # Verify the streamed text
    assert collected_text == "You said: Hello streaming!"


@pytest.mark.asyncio
async def test_anthropic_messages_with_tool_use(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API with tool use."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Define tool
    tools: list[ToolParam] = [
        ToolParam(
            name="get_weather",
            description="Get the current weather in a given location",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    }
                },
                "required": ["location"],
            },
        )
    ]

    # Make request with tools
    response = await client.messages.create(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "What's the weather in San Francisco?"}],
        max_tokens=256,
        tools=tools,
        tool_choice={"type": "any"},
    )

    # Verify response
    assert response.type == "message"
    assert len(response.content) == 2

    # First should be text
    assert response.content[0].type == "text"
    assert "weather" in response.content[0].text.lower()

    # Second should be tool_use
    assert response.content[1].type == "tool_use"
    assert response.content[1].name == "get_weather"
    assert response.content[1].input == {"location": "San Francisco, CA"}
    assert response.stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_anthropic_messages_streaming_with_tool_use(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API streaming with tool use."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Define tool
    tools: list[ToolParam] = [
        ToolParam(
            name="get_weather",
            description="Get the current weather in a given location",
            input_schema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "The city and state, e.g. San Francisco, CA",
                    }
                },
                "required": ["location"],
            },
        )
    ]

    # Stream response with tools
    collected_text = ""
    collected_json = ""
    events = []

    async with client.messages.stream(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "What's the weather in San Francisco?"}],
        max_tokens=256,
        tools=tools,
        tool_choice={"type": "any"},
    ) as stream:
        async for event in stream:
            events.append(event)

            # Collect text and JSON from events
            if hasattr(event, "type"):
                if event.type == "content_block_delta":
                    if hasattr(event, "delta"):
                        if hasattr(event.delta, "text"):
                            collected_text += event.delta.text
                        elif hasattr(event.delta, "partial_json"):
                            collected_json += event.delta.partial_json

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "message_start" in event_types
    assert "content_block_start" in event_types
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types
    assert "message_delta" in event_types
    assert "message_stop" in event_types

    # Verify the content
    assert "weather" in collected_text.lower()
    assert "San Francisco" in collected_json


@pytest.mark.asyncio
async def test_anthropic_messages_with_thinking(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API with thinking blocks."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Make request that triggers thinking
    response = await client.messages.create(
        model="claude-opus-4-1-20250805",
        messages=[
            {"role": "user", "content": "test_thinking: Solve this complex problem"}
        ],
        max_tokens=256,
    )

    # Verify response
    assert response.type == "message"
    assert len(response.content) == 2

    # First should be thinking block
    assert response.content[0].type == "thinking"
    assert "step by step" in response.content[0].thinking
    assert response.content[0].signature is not None

    # Second should be text
    assert response.content[1].type == "text"
    assert "42" in response.content[1].text


@pytest.mark.asyncio
async def test_anthropic_messages_streaming_with_thinking(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API streaming with thinking blocks."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Stream response with thinking
    thinking_text = ""
    answer_text = ""
    signature = ""
    events = []

    async with client.messages.stream(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "test_thinking: Solve this problem"}],
        max_tokens=256,
    ) as stream:
        async for event in stream:
            events.append(event)

            # Collect thinking, text, and signature from events
            if hasattr(event, "type"):
                if event.type == "content_block_delta":
                    if hasattr(event, "delta"):
                        if hasattr(event.delta, "thinking"):
                            thinking_text += event.delta.thinking
                        elif hasattr(event.delta, "text"):
                            answer_text += event.delta.text
                        elif hasattr(event.delta, "signature"):
                            signature = event.delta.signature

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "message_start" in event_types
    assert "content_block_start" in event_types
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types
    assert "message_delta" in event_types
    assert "message_stop" in event_types

    # Verify the content
    assert "step by step" in thinking_text
    assert "42" in answer_text
    assert len(signature) > 0


@pytest.mark.asyncio
async def test_anthropic_messages_content_array_format(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API with content array format in request."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Make request with content array format
    response = await client.messages.create(
        model="claude-opus-4-1-20250805",
        messages=[
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello from content array!"}],
            }
        ],
        max_tokens=256,
    )

    # Verify response
    assert response.type == "message"
    assert response.role == "assistant"
    assert len(response.content) == 1
    assert response.content[0].type == "text"
    assert response.content[0].text == "You said: Hello from content array!"


@pytest.mark.asyncio
async def test_anthropic_messages_web_search_tool(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API with web search tool."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Make request that triggers web search
    response = await client.messages.create(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "test_web_search: Find latest AI news"}],
        max_tokens=256,
    )

    # Verify response
    assert response.type == "message"
    assert len(response.content) == 2

    # First should be text
    assert response.content[0].type == "text"
    assert "search" in response.content[0].text.lower()

    # Second should be server_tool_use (web search)
    # Note: Anthropic SDK might expose this as a different type
    assert response.content[1].type in ["server_tool_use", "tool_use"]
    if hasattr(response.content[1], "name"):
        assert response.content[1].name == "web_search"
    if hasattr(response.content[1], "input"):
        assert response.content[1].input == {"query": "latest AI news"}


@pytest.mark.asyncio
async def test_anthropic_messages_mcp_tool(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API with MCP tool."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Make request that triggers MCP tool
    response = await client.messages.create(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "test_mcp: Use MCP function"}],
        max_tokens=256,
    )

    # Verify response
    assert response.type == "message"
    assert len(response.content) == 2

    # First should be text
    assert response.content[0].type == "text"
    assert "mcp" in response.content[0].text.lower()

    # Second should be tool_use (MCP)
    assert response.content[1].type == "tool_use"
    assert response.content[1].name == "mcp_function"
    assert response.content[1].input == {"param": "value"}


@pytest.mark.asyncio
async def test_anthropic_messages_streaming_web_search(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API streaming with web search tool."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Stream response with web search
    collected_text = ""
    collected_json = ""
    events = []

    async with client.messages.stream(
        model="claude-opus-4-1-20250805",
        messages=[{"role": "user", "content": "test_web_search: Search for AI"}],
        max_tokens=256,
    ) as stream:
        async for event in stream:
            events.append(event)

            # Collect text and JSON from events
            if hasattr(event, "type"):
                if event.type == "content_block_delta":
                    if hasattr(event, "delta"):
                        if hasattr(event.delta, "text"):
                            collected_text += event.delta.text
                        elif hasattr(event.delta, "partial_json"):
                            collected_json += event.delta.partial_json

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "message_start" in event_types
    assert "content_block_start" in event_types
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types

    # Verify the content
    assert "search" in collected_text.lower()
    assert "latest AI news" in collected_json


@pytest.mark.asyncio
async def test_anthropic_messages_streaming_mcp_tool(
    proxy_server_anthropic: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Anthropic Messages API streaming with MCP tool."""
    _server, base_url = proxy_server_anthropic

    # Use Anthropic client
    client = AsyncAnthropic(base_url=base_url)

    # Stream response with MCP tool
    collected_text = ""
    collected_json = ""
    events = []

    async with client.messages.stream(
        model="claude-opus-4-1-20250805",
        messages=[
            {"role": "user", "content": "test_mcp: Use MCP function with streaming"}
        ],
        max_tokens=256,
    ) as stream:
        async for event in stream:
            events.append(event)

            # Collect text and JSON from events
            if hasattr(event, "type"):
                if event.type == "content_block_delta":
                    if hasattr(event, "delta"):
                        if hasattr(event.delta, "text"):
                            collected_text += event.delta.text
                        elif hasattr(event.delta, "partial_json"):
                            collected_json += event.delta.partial_json

    # Verify we received events
    assert len(events) > 0

    # Check key event types were received
    event_types = {e.type for e in events if hasattr(e, "type")}
    assert "message_start" in event_types
    assert "content_block_start" in event_types
    assert "content_block_delta" in event_types
    assert "content_block_stop" in event_types
    assert "message_delta" in event_types
    assert "message_stop" in event_types

    # Verify the content
    assert "mcp" in collected_text.lower()
    assert '"param": "value"' in collected_json or '"param":"value"' in collected_json


# ============ Google generateContent API Tests ============


@pytest.fixture
async def proxy_server_google() -> AsyncGenerator[tuple[AsyncHTTPServer, str], None]:
    """Fixture to create and start the model proxy server for Google testing."""
    from inspect_ai.agent._bridge.sandbox.proxy import model_proxy_server

    # Mock the bridge service for Google
    async def mock_bridge_service_google(
        method: str, json_data: dict[str, Any]
    ) -> dict[str, Any]:
        """Mock implementation of call_bridge_model_service_async for Google."""
        if method == "generate_google":
            # Get the contents from the request
            contents = json_data.get("contents", [])
            tools = json_data.get("tools", [])

            # Check for special test triggers
            last_user_text = ""
            if contents:
                for content in reversed(contents):
                    if content.get("role") == "user":
                        parts = content.get("parts", [])
                        for part in parts:
                            if "text" in part:
                                last_user_text = part["text"]
                                break
                        if last_user_text:
                            break

            # Generate different responses based on content
            if "test_thinking" in last_user_text:
                # Return a thinking response
                return {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "text": "Let me analyze this problem carefully.",
                                        "thought": True,
                                    },
                                    {"text": "The answer is 42."},
                                ],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 20,
                        "candidatesTokenCount": 50,
                        "totalTokenCount": 70,
                        "thoughtsTokenCount": 30,
                    },
                }
            elif "test_web_search" in last_user_text:
                # Return a web search function call response
                return {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": "I'll search for that information."},
                                    {
                                        "functionCall": {
                                            "name": "web_search",
                                            "args": {"query": "latest AI news"},
                                        }
                                    },
                                ],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 20,
                        "candidatesTokenCount": 15,
                        "totalTokenCount": 35,
                    },
                }
            elif tools and "weather" in last_user_text.lower():
                # Return a tool use response
                return {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": "I'll check the weather for you."},
                                    {
                                        "functionCall": {
                                            "name": "get_weather",
                                            "args": {"location": "San Francisco"},
                                        }
                                    },
                                ],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 25,
                        "candidatesTokenCount": 20,
                        "totalTokenCount": 45,
                    },
                }
            else:
                # Default text response
                response_text = (
                    f"You said: {last_user_text}" if last_user_text else "Hello!"
                )
                return {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [{"text": response_text}],
                            },
                            "finishReason": "STOP",
                        }
                    ],
                    "usageMetadata": {
                        "promptTokenCount": 10,
                        "candidatesTokenCount": 15,
                        "totalTokenCount": 25,
                    },
                }
        else:
            raise ValueError(f"Unknown method: {method}")

    # Create server with mocked bridge service
    server = await model_proxy_server(
        port=0,
        call_bridge_model_service_async=mock_bridge_service_google,
    )

    # Start server manually (not using start() which blocks)
    server.server = await asyncio.start_server(
        server._handle_client, server.host, server.port
    )

    # Get the actual port that was assigned
    port = server.server.sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    try:
        yield server, base_url
    finally:
        # Clean up
        if server.server:
            server.server.close()
            await server.server.wait_closed()


@pytest.mark.asyncio
async def test_google_generate_content_non_streaming(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API non-streaming endpoint."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Make request
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[{"role": "user", "parts": [{"text": "Hello, Gemini!"}]}],
    )

    # Verify response structure
    assert response.candidates is not None
    assert len(response.candidates) == 1
    candidate = response.candidates[0]
    assert candidate.content.role == "model"
    parts = candidate.content.parts
    assert len(parts) == 1
    assert parts[0].text == "You said: Hello, Gemini!"
    assert candidate.finish_reason == "STOP"

    # Verify usage metadata
    assert response.usage_metadata is not None
    assert response.usage_metadata.total_token_count == 25


@pytest.mark.asyncio
async def test_google_generate_content_streaming(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API streaming endpoint."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Stream response
    collected_text = ""
    chunks = []

    # Use generate_content_stream for streaming
    async for chunk in await client.aio.models.generate_content_stream(
        model="gemini-2.0-flash",
        contents=[{"role": "user", "parts": [{"text": "Hello streaming!"}]}],
    ):
        chunks.append(chunk)
        # Collect text from the chunk
        if chunk.candidates:
            for part in chunk.candidates[0].content.parts:
                if part.text:
                    collected_text += part.text

    # Verify we received chunks
    assert len(chunks) > 0

    # Verify the streamed text
    assert "You said: Hello streaming!" in collected_text


@pytest.mark.asyncio
async def test_google_generate_content_with_function_calling(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API with function calling."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Make request with tools
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            {
                "role": "user",
                "parts": [{"text": "What's the weather in San Francisco?"}],
            }
        ],
        config=genai.types.GenerateContentConfig(
            tools=[
                {
                    "function_declarations": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "location": {"type": "string"},
                                },
                                "required": ["location"],
                            },
                        }
                    ]
                }
            ],
        ),
    )

    # Verify response structure
    assert response.candidates is not None
    candidate = response.candidates[0]
    parts = candidate.content.parts
    assert len(parts) == 2

    # First part should be text
    assert parts[0].text
    assert "weather" in parts[0].text.lower()

    # Second part should be function call
    assert parts[1].function_call is not None
    function_call = parts[1].function_call
    assert function_call.name == "get_weather"
    assert function_call.args["location"] == "San Francisco"


@pytest.mark.asyncio
async def test_google_generate_content_streaming_with_function_calling(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API streaming with function calling."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Stream response with tools
    collected_text = ""
    function_call_name = ""
    function_call_args = {}
    chunks = []

    async for chunk in await client.aio.models.generate_content_stream(
        model="gemini-2.0-flash",
        contents=[
            {
                "role": "user",
                "parts": [{"text": "What's the weather in San Francisco?"}],
            }
        ],
        config=genai.types.GenerateContentConfig(
            tools=[
                {
                    "function_declarations": [
                        {
                            "name": "get_weather",
                            "description": "Get the current weather",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "location": {"type": "string"},
                                },
                                "required": ["location"],
                            },
                        }
                    ]
                }
            ],
        ),
    ):
        chunks.append(chunk)
        # Collect text and function calls from the chunk
        if chunk.candidates:
            for part in chunk.candidates[0].content.parts:
                if part.text:
                    collected_text += part.text
                elif part.function_call:
                    function_call_name = part.function_call.name
                    function_call_args = part.function_call.args

    # Verify we received chunks
    assert len(chunks) > 0

    # Verify the streamed content
    assert "weather" in collected_text.lower()
    assert function_call_name == "get_weather"
    assert function_call_args["location"] == "San Francisco"


@pytest.mark.asyncio
async def test_google_generate_content_with_thinking(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API with thinking/reasoning."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Make request with thinking configuration
    response = await client.aio.models.generate_content(
        model="gemini-2.5-flash-thinking",
        contents=[
            {
                "role": "user",
                "parts": [{"text": "test_thinking: Solve this complex problem"}],
            }
        ],
        config=genai.types.GenerateContentConfig(
            thinking_config=genai.types.ThinkingConfig(thinking_budget=1024),
        ),
    )

    # Verify response structure
    assert response.candidates is not None
    candidate = response.candidates[0]
    parts = candidate.content.parts

    # Should have thought part and answer part
    assert len(parts) == 2

    # First part should be thought
    thought_part = parts[0]
    assert thought_part.text == "Let me analyze this problem carefully."
    assert thought_part.thought is True

    # Second part should be answer
    answer_part = parts[1]
    assert answer_part.text == "The answer is 42."

    # Verify usage metadata includes thinking tokens
    assert response.usage_metadata is not None
    assert response.usage_metadata.thoughts_token_count == 30


@pytest.mark.asyncio
async def test_google_generate_content_streaming_with_thinking(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API streaming with thinking/reasoning."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Stream response with thinking
    thought_text = ""
    answer_text = ""
    chunks = []

    async for chunk in await client.aio.models.generate_content_stream(
        model="gemini-2.5-flash-thinking",
        contents=[
            {
                "role": "user",
                "parts": [{"text": "test_thinking: Solve this problem"}],
            }
        ],
        config=genai.types.GenerateContentConfig(
            thinking_config=genai.types.ThinkingConfig(thinking_budget=1024),
        ),
    ):
        chunks.append(chunk)
        # Collect text from the chunk, separating thoughts from answers
        if chunk.candidates:
            for part in chunk.candidates[0].content.parts:
                if part.text:
                    if hasattr(part, "thought") and part.thought:
                        thought_text += part.text
                    else:
                        answer_text += part.text

    # Verify we received chunks
    assert len(chunks) > 0

    # Verify the streamed text
    assert "Let me analyze this problem carefully." in thought_text
    assert "The answer is 42." in answer_text


@pytest.mark.asyncio
async def test_google_generate_content_web_search_tool(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API with web search tool."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Make request with web search tool
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            {
                "role": "user",
                "parts": [{"text": "test_web_search: Find latest AI news"}],
            }
        ],
        config=genai.types.GenerateContentConfig(
            tools=[{"google_search": {}}],
        ),
    )

    # Verify response structure
    assert response.candidates is not None
    candidate = response.candidates[0]
    parts = candidate.content.parts

    # Should have text and function call for web_search
    assert len(parts) == 2
    assert parts[1].function_call is not None
    function_call = parts[1].function_call
    assert function_call.name == "web_search"
    assert function_call.args["query"] == "latest AI news"


@pytest.mark.asyncio
async def test_google_generate_content_streaming_web_search(
    proxy_server_google: tuple[AsyncHTTPServer, str],
) -> None:
    """Test Google generateContent API streaming with web search."""
    _server, base_url = proxy_server_google

    # Use Google client
    client = genai.Client(api_key="test", http_options={"base_url": base_url})

    # Stream response with web search
    collected_text = ""
    function_call_name = ""
    function_call_args = {}
    chunks = []

    async for chunk in await client.aio.models.generate_content_stream(
        model="gemini-2.0-flash",
        contents=[
            {
                "role": "user",
                "parts": [{"text": "test_web_search: Find latest AI news"}],
            }
        ],
        config=genai.types.GenerateContentConfig(
            tools=[{"google_search": {}}],
        ),
    ):
        chunks.append(chunk)
        # Collect text and function calls from the chunk
        if chunk.candidates:
            for part in chunk.candidates[0].content.parts:
                if part.text:
                    collected_text += part.text
                elif part.function_call:
                    function_call_name = part.function_call.name
                    function_call_args = part.function_call.args

    # Verify we received chunks
    assert len(chunks) > 0

    # Verify the streamed content
    assert "search" in collected_text.lower()
    assert function_call_name == "web_search"
    assert function_call_args["query"] == "latest AI news"
