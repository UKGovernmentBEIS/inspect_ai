// @ts-check
import { html } from "htm/preact";

import { ApplicationIcons } from "../appearance/Icons.mjs";

import { MessageContent } from "./MessageContent.mjs";
import { ExpandablePanel } from "./ExpandablePanel.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { resolveToolInput, ToolCallView } from "./Tools.mjs";

/**
 * Renders the ChatView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the chat view.
 * @param {import("../types/log").Messages} props.messages - The array of chat messages.
 * @param {Object} [props.style] - Inline styles for the chat view.
 * @param {boolean} props.indented - Whether the chatview has indented messages
 * @param {boolean} [props.numbered] - Whether the chatview is numbered
 * @returns {import("preact").JSX.Element} The component.
 */
export const ChatView = ({
  id,
  messages,
  style,
  indented,
  numbered = true,
}) => {
  // Filter tool messages into a sidelist that the chat stream
  // can use to lookup the tool responses

  /**
   * @type {Array<{message: import("../types/log").ChatMessageAssistant | import("../types/log").ChatMessageSystem | import("../types/log").ChatMessageUser, toolOutput?: import("../types/log").ChatMessageTool}>}
   */
  const resolvedMessages = [];
  for (const message of messages) {
    if (message.role === "tool") {
      // Add this tool message onto the previous message
      if (resolvedMessages.length > 0) {
        const msg = resolvedMessages[resolvedMessages.length - 1];
        msg.toolOutput = message;
      }
    } else {
      resolvedMessages.push({ message });
    }
  }

  // Capture system messages (there could be multiple)
  /**
   * @type {Array<import("../types/log").ChatMessageSystem>}
   */
  const systemMessages = [];
  const collapsedMessages = resolvedMessages
    .map((resolved) => {
      if (resolved.message.role === "system") {
        systemMessages.push(resolved.message);
      }
      return resolved;
    })
    .filter((resolved) => {
      return resolved.message.role !== "system";
    });

  // Collapse system messages
  /**
   * @type {Array<import("../types/log").ContentImage | import("../types/log").ContentText>}
   */
  const systemContent = [];
  for (const systemMessage of systemMessages) {
    const contents = Array.isArray(systemMessage.content)
      ? systemMessage.content
      : [systemMessage.content];
    systemContent.push(...contents.map(normalizeContent));
  }

  /**
   * @type {import("../types/log").ChatMessageSystem}
   */
  const systemMessage = {
    role: "system",
    content: systemContent,
    source: "input",
  };

  // Converge them
  if (systemMessage && systemMessage.content.length > 0) {
    collapsedMessages.unshift({ message: systemMessage });
  }

  const result = html`
    <div style=${style}>
      ${collapsedMessages.map((msg, index) => {
        if (collapsedMessages.length > 1 && numbered) {
          return html` <div
            style=${{
              display: "grid",
              gridTemplateColumns: "max-content auto",
              columnGap: "0.4em",
            }}
          >
            <div
              style=${{
                fontSize: FontSize.smaller,
                ...TextStyle.secondary,
                marginTop: "0.1em",
              }}
            >
              ${index + 1}
            </div>
            <${ChatMessage}
              id=${`${id}-chat-messages`}
              message=${msg.message}
              toolMessage=${msg.toolOutput}
              indented=${indented}
            />
          </div>`;
        } else {
          return html` <${ChatMessage}
            id=${`${id}-chat-messages`}
            message=${msg.message}
            toolMessage=${msg.toolOutput}
            indented=${indented}
          />`;
        }
      })}
    </div>
  `;

  return result;
};

/**
 * Ensure that content is a proper content type
 *
 * @param {import("../types/log").ContentText | import("../types/log").ContentImage | string} content - The properties passed to the component.
 * @returns {import("../types/log").ContentText | import("../types/log").ContentImage} The component.
 */
const normalizeContent = (content) => {
  if (typeof content === "string") {
    return {
      type: "text",
      text: content,
    };
  } else {
    return content;
  }
};

const ChatMessage = ({ id, message, toolMessage, indented }) => {
  const collapse = message.role === "system";
  return html`
    <div
      class="${message.role}"
      style=${{
        fontSize: FontSize.base,
        fontWeight: "300",
        paddingBottom: ".5em",
        marginLeft: "0",
        marginRight: "0",
        opacity: message.role === "system" ? "0.7" : "1",
        whiteSpace: "normal",
      }}
    >
      <div style=${{
        display: "grid",
        gridTemplateColumns: "max-content auto",
        columnGap: "0.3em",
        fontWeight: "500",
        marginBottom: "0.5em",
        ...TextStyle.label,
      }}>
        <i class="${iconForMsg(message)}"></i>
        ${message.role}
      </div>
      <div style=${{ marginLeft: indented ? "1.1rem" : "0", paddingBottom: indented ? "0.8rem" : "0" }}>
      <${ExpandablePanel} collapse=${collapse}>
        <${MessageContents}
          key=${`${id}-contents`}
          message=${message}
          toolMessage=${toolMessage}
        />
      </${ExpandablePanel}>
      </div>
    </div>
  `;
};

const MessageContents = ({ message, toolMessage }) => {
  if (message.tool_calls && message.tool_calls.length) {
    const result = [];

    // If the message contains content, render that.
    if (message.content) {
      result.push(
        html`<div style=${{ marginBottom: "1em" }}>
          <${MessageContent} contents=${message.content} />
        </div>`,
      );
    }

    // Render the tool calls made by this message
    const toolCalls = message.tool_calls.map((tool_call) => {
      // Extract tool input
      const { input, functionCall, inputType } = resolveToolInput(
        tool_call.function,
        tool_call.arguments,
      );

      // Resolve the tool output
      const resolvedToolOutput = resolveToolMessage(toolMessage);
      return html`<${ToolCallView}
        functionCall=${functionCall}
        input=${input}
        inputType=${inputType}
        output=${resolvedToolOutput}
      />`;
    });

    if (toolCalls) {
      result.push(...toolCalls);
    }
    return result;
  } else {
    return html`<${MessageContent} contents=${message.content} />`;
  }
};

export const iconForMsg = (msg) => {
  if (msg.role === "user") {
    return ApplicationIcons.role.user;
  } else if (msg.role === "system") {
    return ApplicationIcons.role.system;
  } else if (msg.role === "tool") {
    return ApplicationIcons.role.tool;
  } else if (msg.role === "assistant") {
    return ApplicationIcons.role.assistant;
  } else {
    return ApplicationIcons.role.unknown;
  }
};

const resolveToolMessage = (toolMessage) => {
  if (!toolMessage) {
    return undefined;
  }

  const content =
    toolMessage.error?.message || toolMessage.tool_error || toolMessage.content;
  if (typeof content === "string") {
    return [
      {
        type: "tool",
        content,
      },
    ];
  } else {
    return content.map((con) => {
      if (typeof content === "string") {
        return {
          type: "tool",
          content,
        };
      } else if (con.type === "text") {
        return {
          content,
          type: "tool",
        };
      } else if (con.type === "image") {
        return {
          content,
          type: "tool",
        };
      }
    });
  }
};
