import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../../@types/log";
import { MessageContent } from "./MessageContent";
import { resolveToolInput } from "./tools/tool";
import { ToolCallView } from "./tools/ToolCallView";

import clsx from "clsx";
import { FC, Fragment } from "react";
import { ContentTool } from "../../../app/types";
import styles from "./MessageContents.module.css";
import { ChatViewToolCallStyle, Citation } from "./types";

interface MessageContentsProps {
  id: string;
  message: ChatMessageAssistant | ChatMessageSystem | ChatMessageUser;
  toolMessages: ChatMessageTool[];
  toolCallStyle: ChatViewToolCallStyle;
}

export interface MessagesContext {
  citations: Citation[];
}

export const defaultContext = () => {
  return {
    citeOffset: 0,
    citations: [],
  };
};

export const MessageContents: FC<MessageContentsProps> = ({
  id,
  message,
  toolMessages,
  toolCallStyle,
}) => {
  const context: MessagesContext = defaultContext();
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
            <code className={clsx(styles.codeCompact)}>
              tool: {functionCall}
            </code>
          </div>
        );
      } else if (toolCallStyle === "omit") {
        return undefined;
      } else {
        return (
          <ToolCallView
            id={`${id}-tool-call`}
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
        {message.content && (
          <div className={styles.content}>
            <MessageContent contents={message.content} context={context} />
          </div>
        )}
        {toolCalls}
      </Fragment>
    );
  } else {
    return (
      <>
        {message.content && (
          <MessageContent contents={message.content} context={context} />
        )}
      </>
    );
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
            refusal: null,
            internal: null,
            citations: null,
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
                refusal: null,
                internal: null,
                citations: null,
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
