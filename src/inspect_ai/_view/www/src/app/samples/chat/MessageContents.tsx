import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
  ContentImage,
  ContentText,
} from "../../../@types/log";
import { MessageContent } from "./MessageContent";
import { resolveToolInput, substituteToolCallContent } from "./tools/tool";
import { ToolCallView } from "./tools/ToolCallView";
import {
  buildSelfAnnotation,
  BROWSER_TOOL_FUNCTIONS,
  isBrowserScreenshot,
} from "./tools/browserActionUtils";

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

      // For visual browser actions (click/scroll/type), find the preceding
      // screenshot tool call to show as the "Input" tab with annotation overlay.
      const toolArgs = tool_call.arguments as Record<string, unknown>;
      const selfAnnotation = buildSelfAnnotation(tool_call.function, toolArgs);
      const inputScreenshot = selfAnnotation
        ? findPrecedingScreenshotOutput(allToolCalls, toolMessages, idx)
        : undefined;

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
            selfAnnotation={selfAnnotation}
            inputScreenshot={inputScreenshot}
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

/**
 * Walk backward from the current tool call index to find the preceding
 * browser screenshot and return its output as normalized content.
 * Used to populate the "Input" tab on visual browser actions.
 */
const findPrecedingScreenshotOutput = (
  allToolCalls: ReadonlyArray<{
    id?: string;
    function: string;
    arguments: unknown;
  }>,
  toolMessages: ChatMessageTool[],
  currentIndex: number,
): (ContentText | ContentImage)[] | undefined => {
  for (let j = currentIndex - 1; j >= 0; j--) {
    const prevCall = allToolCalls[j];
    if (!BROWSER_TOOL_FUNCTIONS.has(prevCall.function)) break;
    const prevArgs = prevCall.arguments as Record<string, unknown>;
    if (isBrowserScreenshot(prevCall.function, prevArgs)) {
      // Found the preceding screenshot — get its tool message output.
      let prevToolMsg: ChatMessageTool | undefined;
      if (prevCall.id) {
        prevToolMsg = toolMessages.find(
          (msg) => msg.tool_call_id === prevCall.id,
        );
      } else {
        prevToolMsg = toolMessages[j];
      }
      if (!prevToolMsg) return undefined;
      const resolved = resolveToolMessage(prevToolMsg);
      // Extract image content from the resolved ContentTool wrappers.
      const images: (ContentText | ContentImage)[] = [];
      for (const ct of resolved) {
        for (const item of ct.content) {
          if (item.type === "image" || item.type === "text") {
            images.push(item);
          }
        }
      }
      return images.length > 0 ? images : undefined;
    }
  }
  return undefined;
};
