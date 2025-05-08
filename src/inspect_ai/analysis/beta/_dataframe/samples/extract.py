from typing import Callable

from jsonpath_ng import JSONPath  # type: ignore
from pydantic import JsonValue

from inspect_ai.analysis.beta._dataframe.extract import auto_id
from inspect_ai.log._log import EvalSample, EvalSampleSummary
from inspect_ai.model._chat_message import ChatMessageAssistant, ChatMessageTool


def sample_messages_as_str(sample: EvalSample) -> str:
    # format each message for the transcript
    transcript: list[str] = []
    for msg in sample.messages:
        role = msg.role
        content = msg.text.strip() if msg.text else ""

        # assistant messages with tool calls
        if isinstance(msg, ChatMessageAssistant) and msg.tool_calls is not None:
            entry = f"{role}:\n{content}\n"

            for tool in msg.tool_calls:
                func_name = tool.function
                args = tool.arguments

                if isinstance(args, dict):
                    args_text = "\n".join(f"{k}: {v}" for k, v in args.items())
                    entry += f"\nTool Call: {func_name}\nArguments:\n{args_text}"
                else:
                    entry += f"\nTool Call: {func_name}\nArguments: {args}"

            transcript.append(entry)

        # tool responses with errors
        elif isinstance(msg, ChatMessageTool) and msg.error is not None:
            func_name = msg.function or "unknown"
            entry = f"{role}:\n{content}\n\nError in tool call '{func_name}':\n{msg.error.message}\n"
            transcript.append(entry)

        # normal messages
        else:
            transcript.append(f"{role}:\n{content}\n")

    return "\n".join(transcript)


def sample_path_requires_full(
    path: str
    | JSONPath
    | Callable[[EvalSampleSummary], JsonValue]
    | Callable[[EvalSample], JsonValue],
) -> bool:
    if callable(path):
        return False
    else:
        path = str(path)
        return any(
            [
                path.startswith(prefix)
                for prefix in [
                    "choices",
                    "sandbox",
                    "files",
                    "setup",
                    "messages",
                    "output",
                    "store",
                    "events",
                    "uuid",
                    "error_retries",
                    "attachments",
                ]
            ]
        )


def auto_sample_id(eval_id: str, sample: EvalSample | EvalSampleSummary) -> str:
    return auto_id(eval_id, f"{sample.id}_{sample.epoch}")


def auto_detail_id(sample_id: str, name: str, index: int) -> str:
    return auto_id(sample_id, f"{name}_{index}")
