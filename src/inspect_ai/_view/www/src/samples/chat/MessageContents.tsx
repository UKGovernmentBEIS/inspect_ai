import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../types/log";
import { MessageContent } from "./MessageContent";
import { resolveToolInput } from "./tools/tool";
import { ToolCallView } from "./tools/ToolCallView";

import { ContentTool } from "../../types";
import styles from "./MessageContents.module.css";

interface MessageContentsProps {
  message: ChatMessageAssistant | ChatMessageSystem | ChatMessageUser;
  toolMessages: ChatMessageTool[];
  toolCallStyle: "compact" | "complete";
}

export const MessageContents: React.FC<MessageContentsProps> = ({
  message,
  toolMessages,
  toolCallStyle,
}) => {
  if (
    message.role === "assistant" &&
    message.tool_calls &&
    message.tool_calls.length
  ) {
    const result = [];
    // If the message contains content, render that.
    if (message.content) {
      result.push(
        <div className={styles.content}>
          <MessageContent contents={message.content} />
        </div>,
      );
    }

    // Render the tool calls made by this message
    const toolCalls = message.tool_calls.map((tool_call, idx) => {
      // Extract tool input
      const { input, functionCall, inputType } = resolveToolInput(
        tool_call.function,
        tool_call.arguments,
      );

      let toolMessage;
      if (tool_call.id) {
        toolMessage = toolMessages.find((msg) => {
          return msg.tool_call_id === tool_call.id;
        });
      } else {
        toolMessage = toolMessages[idx];
      }

      // Resolve the tool output
      const resolvedToolOutput = resolveToolMessage(toolMessage);
      if (toolCallStyle === "compact") {
        return <code>tool: {functionCall}</code>;
      } else {
        return (
          <ToolCallView
            functionCall={functionCall}
            input={input}
            inputType={inputType}
            output={resolvedToolOutput}
          />
        );
      }
    });

    if (toolCalls) {
      result.push(...toolCalls);
    }
    return result;
  } else {
    return <MessageContent contents={message.content} />;
  }
};

const resolveToolMessage = (toolMessage?: ChatMessageTool): ContentTool[] => {
  if (!toolMessage) {
    return [];
  }

  const content =
    toolMessage.error !== null && toolMessage.error
      ? toolMessage.error.message
      : toolMessage.content;
  if (typeof content === "string") {
    return [
      {
        type: "tool",
        content: [
          {
            type: "text",
            text: content,
          },
        ],
      },
    ];
  } else {
    const result = content
      .map((con) => {
        if (typeof con === "string") {
          return {
            type: "tool",
            content: [
              {
                type: "text",
                text: con,
              },
            ],
          } as ContentTool;
        } else if (con.type === "text") {
          return {
            content: [con],
            type: "tool",
          } as ContentTool;
        } else if (con.type === "image") {
          return {
            content: [con],
            type: "tool",
          } as ContentTool;
        }
      })
      .filter((con) => con !== undefined);
    return result;
  }
};
