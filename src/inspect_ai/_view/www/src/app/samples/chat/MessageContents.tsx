import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
} from "../../../@types/log";
import { MessageContent } from "./MessageContent";
import { resolveToolInput, substituteToolCallContent } from "./tools/tool";
import { ToolCallView } from "./tools/ToolCallView";

import clsx from "clsx";
import { FC, Fragment } from "react";
import { ContentTool } from "../../../app/types";
import styles from "./MessageContents.module.css";
import { ChatViewToolCallStyle, Citation } from "./types";

interface MessageContentsProps {
  id: string;
  message:
    | ChatMessageAssistant
    | ChatMessageSystem
    | ChatMessageUser
    | ChatMessageTool;
  toolMessages: ChatMessageTool[];
  toolCallStyle: ChatViewToolCallStyle;
}

export interface MessagesContext {
  citeOffset: number;
  citations: Citation[];
  role: "system" | "user" | "assistant" | "tool" | "unknown";
}

export const defaultContext = (
  role: "system" | "user" | "assistant" | "tool" | "unknown",
) => {
  return {
    citeOffset: 0,
    citations: [],
    role,
  };
};

export const MessageContents: FC<MessageContentsProps> = ({
  id,
  message,
  toolMessages,
  toolCallStyle,
}) => {
  const context: MessagesContext = defaultContext(message.role);
  if (
    message.role === "assistant" &&
    message.tool_calls &&
    message.tool_calls.length
  ) {
    // Render the tool calls made by this message
    const allToolCalls = message.tool_calls;
    const toolCalls = allToolCalls.map((tool_call, idx) => {
      // Extract tool input
      const { input, description, functionCall, contentType } =
        resolveToolInput(tool_call.function, tool_call.arguments);

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

      // For screenshot tool calls, look FORWARD to find the next visual
      // browser action (click/scroll/type). The annotation shows what is
      // ABOUT TO happen on this screen. Skip non-visual actions like
      // get_page_text that don't have coordinates.
      const visualActions = new Set([
        "left_click",
        "right_click",
        "middle_click",
        "double_click",
        "triple_click",
        "scroll",
        "type",
        "key",
      ]);
      let precedingAction: Record<string, unknown> | undefined;
      if (
        tool_call.function === "browser" &&
        (tool_call.arguments as Record<string, unknown>)?.action ===
          "screenshot"
      ) {
        for (let j = idx + 1; j < allToolCalls.length; j++) {
          const nextCall = allToolCalls[j];
          if (nextCall.function !== "browser") break;
          const nextArgs = nextCall.arguments as Record<string, unknown>;
          const nextAction = nextArgs?.action as string | undefined;
          if (nextAction === "screenshot" || nextAction === "navigate") break;
          if (nextAction && visualActions.has(nextAction)) {
            precedingAction = nextArgs;
            break;
          }
          // non-visual (get_page_text, etc.) — keep searching
        }
      }

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
            precedingBrowserAction={precedingAction}
            description={description}
            contentType={contentType}
            output={resolvedToolOutput}
            collapsible={false}
            view={
              tool_call.view
                ? substituteToolCallContent(
                    tool_call.view,
                    tool_call.arguments as Record<string, unknown>,
                  )
                : undefined
            }
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
