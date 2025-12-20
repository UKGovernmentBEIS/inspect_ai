"""
Claude Code CLI provider for inspect_ai.

Uses the `claude` CLI to run evals via Claude Pro/Max/Team subscription
instead of per-token API billing.

Usage:
    inspect eval inspect_evals/arc_easy --model claude-code/sonnet --limit 100
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

# Short aliases for convenience
MODEL_ALIASES: dict[str, str | None] = {
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
    "haiku": "claude-haiku-4-20250514",
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
    $0 per eval - just uses your existing subscription.

    Examples:
        inspect eval task.py --model claude-code/sonnet
        inspect eval task.py --model claude-code/opus
        inspect eval task.py --model claude-code/default

    Limitations:
        - Sequential only (max_connections=1) - CLI doesn't support parallel
        - No tool/function calling - Claude Code has its own tool system
        - Token counts are estimated (CLI doesn't report exact usage)
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
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

    def max_connections(self) -> int:
        """CLI is sequential - one request at a time."""
        return 1

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        """Generate a response using the Claude Code CLI."""
        # Tool use not supported - Claude Code has its own tools
        if tools:
            raise NotImplementedError(
                "Claude Code provider does not support custom tools. "
                "The CLI has its own built-in tool ecosystem."
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
        ]

        # Add model flag if not using default
        if self._resolved_model:
            cmd.extend(["--model", self._resolved_model])

        # Run subprocess in thread pool (blocking call)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._run_cli, cmd, prompt)

        return result

    def _run_cli(self, cmd: list[str], prompt: str) -> ModelOutput:
        """Execute the Claude CLI and parse the response."""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )
        except subprocess.TimeoutExpired:
            return ModelOutput.from_content(
                model=self.model_name,
                content="",
                stop_reason="unknown",
                error="Claude Code CLI timed out after 5 minutes",
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

        # Parse response
        content = self._parse_output(proc.stdout)

        # Estimate token usage (rough: ~4 chars per token)
        input_tokens = len(prompt) // 4
        output_tokens = len(content) // 4

        return ModelOutput(
            model=self.model_name,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=content,
                        model=self.model_name,
                        source="generate",
                    ),
                    stop_reason="stop",
                )
            ],
            usage=ModelUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
        )

    def _parse_output(self, stdout: str) -> str:
        """Parse Claude Code CLI output.

        The CLI can output JSON with a 'result' field,
        or plain text depending on the response.
        """
        stdout = stdout.strip()
        if not stdout:
            return ""

        # Try JSON first
        try:
            data = json.loads(stdout)
            # Claude Code JSON format has 'result' field
            if isinstance(data, dict):
                if "result" in data:
                    return str(data["result"])
                if "content" in data:
                    return str(data["content"])
                if "text" in data:
                    return str(data["text"])
            # If it's just a string in JSON, use it
            if isinstance(data, str):
                return data
        except json.JSONDecodeError:
            pass

        # Fall back to raw text
        return stdout
