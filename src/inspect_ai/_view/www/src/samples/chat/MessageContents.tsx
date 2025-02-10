import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../types/log";
import { MessageContent } from "./MessageContent";
import { resolveToolInput } from "./tools/tool";
import { ToolCallView } from "./tools/ToolCallView";

import { Fragment } from "react";
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
    // Render the tool calls made by this message
    const toolCalls = message.tool_calls.map((tool_call, idx) => {
      // Extract tool input
      const { input, functionCall, highlightLanguage } = resolveToolInput(
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
        return (
          <div key={`tool-call-${idx}`}>
            <code>tool: {functionCall}</code>
          </div>
        );
      } else {
        return (
          <ToolCallView
            key={`tool-call-${idx}`}
            functionCall={functionCall}
            input={input}
            highlightLanguage={highlightLanguage}
            output={resolvedToolOutput}
          />
        );
      }
    });

    return (
      <Fragment>
        <div className={styles.content}>
          {message.content ? (
            <MessageContent contents={message.content} />
          ) : undefined}
        </div>
        {toolCalls}
      </Fragment>
    );
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
