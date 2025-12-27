"""
Claude Code CLI provider for inspect_ai.

Uses the `claude` CLI to run evals via Claude Pro/Max/Team subscription
instead of per-token API billing.

Usage:
    inspect eval inspect_evals/arc_easy --model claude-code/sonnet --limit 100

Model args:
    skip_permissions: bool - Skip permission prompts (default: True for automation)
    timeout: int - CLI timeout in seconds (default: 300)
"""

import asyncio
import json
import os
import shutil
import subprocess
from typing import Any

from inspect_ai.tool import ToolChoice, ToolInfo

from .._chat_message import ChatMessage, ChatMessageAssistant
from .._generate_config import GenerateConfig
from .._model import ModelAPI
from .._model_output import ChatCompletionChoice, ModelOutput, ModelUsage

# Short aliases for convenience - using Claude 4.5 models (latest)
MODEL_ALIASES: dict[str, str | None] = {
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-5-20251101",
    "haiku": "claude-haiku-4-5-20251001",
    # Allow "default" to use whatever Claude Code defaults to
    "default": None,
}


def find_claude_cli() -> str:
    """Find the claude CLI executable.

    Checks CLAUDE_CODE_COMMAND env var first (for custom paths),
    then falls back to PATH lookup.
    """
    # Check env var first (like Goose does)
    custom_cmd = os.environ.get("CLAUDE_CODE_COMMAND")
    if custom_cmd:
        # Could be a full path or just a command name
        if os.path.isfile(custom_cmd):
            return custom_cmd
        # Try to find it in PATH
        found = shutil.which(custom_cmd)
        if found:
            return found
        # Use as-is and let subprocess handle errors
        return custom_cmd

    # Standard PATH lookup
    claude_path = shutil.which("claude")
    if claude_path:
        return claude_path

    raise RuntimeError(
        "Claude Code CLI not found.\n\n"
        "Install it with:\n"
        "  npm install -g @anthropic-ai/claude-code\n\n"
        "Or set CLAUDE_CODE_COMMAND environment variable to the full path.\n"
        "Make sure to authenticate with: claude auth"
    )


def messages_to_prompt(messages: list[ChatMessage]) -> str:
    """Convert chat messages to a single prompt string.

    Claude Code expects a single prompt, not a message array,
    so we concatenate with role prefixes.
    """
    parts = []
    for msg in messages:
        role = msg.role.capitalize()
        text = msg.text if hasattr(msg, "text") else str(msg.content)
        parts.append(f"[{role}]: {text}")
    return "\n\n".join(parts)


class ClaudeCodeAPI(ModelAPI):
    """Claude Code CLI provider.

    Uses your Claude Pro/Max/Team subscription via the `claude` CLI.
    Uses your existing subscription instead of per-token API billing.

    Examples:
        inspect eval task.py --model claude-code/sonnet
        inspect eval task.py --model claude-code/opus
        inspect eval task.py --model claude-code/default

    Model args:
        skip_permissions: Skip permission prompts (default: True)
        timeout: CLI timeout in seconds (default: 300)
        max_connections: Number of concurrent CLI processes (default: 1)

    Limitations:
        - No custom tool/function calling - uses --tools "" to disable
          Claude Code's built-in tools for clean eval responses
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        skip_permissions: bool = True,
        timeout: int = 300,
        max_connections: int = 1,
        **model_args: Any,
    ) -> None:
        # Resolve model name
        resolved_model = MODEL_ALIASES.get(model_name, model_name)
        display_name = resolved_model or "claude-code/default"

        super().__init__(
            model_name=display_name,
            base_url=base_url,
            api_key=api_key,  # Not used - CLI handles auth
            config=config,
        )

        self._cli_path = find_claude_cli()
        self._model_arg = model_name
        self._resolved_model = resolved_model
        self._skip_permissions = skip_permissions
        self._timeout = timeout
        self._max_connections = max_connections

    def max_connections(self) -> int:
        """Number of concurrent CLI processes to run."""
        return self._max_connections

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        """Generate a response using the Claude Code CLI."""
        # Tool use not supported - Claude Code has its own tools which we disable
        if tools:
            raise NotImplementedError(
                "Claude Code provider does not support custom tools. "
                "The CLI's built-in tools are disabled for clean eval responses."
            )

        # Convert messages to prompt
        prompt = messages_to_prompt(input)

        # Build CLI command
        cmd = [
            self._cli_path,
            "-p",
            prompt,
            "--output-format",
            "json",
            "--tools",
            "",  # Disable all built-in tools for clean evals
        ]

        # Add model flag if not using default
        if self._resolved_model:
            cmd.extend(["--model", self._resolved_model])

        # Skip permission prompts for automation
        if self._skip_permissions:
            cmd.append("--dangerously-skip-permissions")

        # Run subprocess in thread pool (blocking call)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._run_cli, cmd, prompt, self._timeout
        )

        return result

    def _run_cli(self, cmd: list[str], prompt: str, timeout: int) -> ModelOutput:
        """Execute the Claude CLI and parse the response."""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error=f"Claude Code CLI timed out after {timeout} seconds",
            )
        except FileNotFoundError:
            return ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error=f"Claude Code CLI not found at: {self._cli_path}",
            )
        except Exception as e:
            return ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error=f"Claude Code CLI error: {e}",
            )

        # Handle non-zero exit
        if proc.returncode != 0:
            error_msg = proc.stderr.strip() or f"Exit code {proc.returncode}"
            return ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error=f"Claude Code CLI failed: {error_msg}",
            )

        # Parse JSON response
        return self._parse_json_response(proc.stdout, prompt)

    def _parse_json_response(self, stdout: str, prompt: str) -> ModelOutput:
        """Parse Claude Code CLI JSON output.

        The CLI returns JSON with result, usage, and cost information.
        """
        stdout = stdout.strip()
        if not stdout:
            return ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error="Empty response from Claude Code CLI",
            )

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return self._fallback_text_response(stdout, prompt)

        content = self._extract_content(data)
        usage = self._extract_usage(data)
        metadata = self._extract_metadata(data, usage)
        error = self._extract_error(data)

        return ModelOutput(
            model=self.model_name,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=content,
                        model=self.model_name,
                        source="generate",
                    ),
                    stop_reason="stop" if not error else "unknown",
                )
            ],
            usage=ModelUsage(
                input_tokens=usage["input"],
                output_tokens=usage["output"],
                total_tokens=usage["total"],
            ),
            metadata=metadata if metadata else None,
            error=error,
        )

    def _fallback_text_response(self, stdout: str, prompt: str) -> ModelOutput:
        """Create a response when JSON parsing fails."""
        return ModelOutput(
            model=self.model_name,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=stdout,
                        model=self.model_name,
                        source="generate",
                    ),
                    stop_reason="stop",
                )
            ],
            usage=ModelUsage(
                input_tokens=len(prompt) // 4,
                output_tokens=len(stdout) // 4,
                total_tokens=(len(prompt) + len(stdout)) // 4,
            ),
        )

    def _extract_content(self, data: Any) -> str:
        """Extract the response content from parsed JSON."""
        if isinstance(data, dict):
            return str(data.get("result", data.get("content", data.get("text", ""))))
        elif isinstance(data, str):
            return data
        return ""

    def _extract_usage(self, data: Any) -> dict[str, int]:
        """Extract token usage from parsed JSON."""
        usage_data = data.get("usage", {}) if isinstance(data, dict) else {}
        input_tokens = usage_data.get("input_tokens", 0)
        output_tokens = usage_data.get("output_tokens", 0)
        cache_creation = usage_data.get("cache_creation_input_tokens", 0)
        cache_read = usage_data.get("cache_read_input_tokens", 0)

        return {
            "input": input_tokens,
            "output": output_tokens,
            "cache_creation": cache_creation,
            "cache_read": cache_read,
            "total": input_tokens + output_tokens + cache_creation,
        }

    def _extract_metadata(
        self, data: Any, usage: dict[str, int]
    ) -> dict[str, Any] | None:
        """Extract metadata (cost, timing, etc.) from parsed JSON."""
        if not isinstance(data, dict):
            return None

        metadata: dict[str, Any] = {}

        # Cost and timing info
        if "total_cost_usd" in data:
            metadata["cost_usd"] = data["total_cost_usd"]
        if "duration_ms" in data:
            metadata["duration_ms"] = data["duration_ms"]
        if "duration_api_ms" in data:
            metadata["duration_api_ms"] = data["duration_api_ms"]
        if "session_id" in data:
            metadata["session_id"] = data["session_id"]

        # Cache token info
        if usage["cache_creation"] > 0:
            metadata["cache_creation_input_tokens"] = usage["cache_creation"]
        if usage["cache_read"] > 0:
            metadata["cache_read_input_tokens"] = usage["cache_read"]

        return metadata if metadata else None

    def _extract_error(self, data: Any) -> str | None:
        """Extract error message from parsed JSON if present."""
        if not isinstance(data, dict):
            return None

        if data.get("is_error"):
            return str(data.get("result", "Unknown error"))
        elif data.get("type") == "error":
            return str(data.get("result", data.get("message", "Unknown error")))

        return None
