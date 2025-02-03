// @ts-check
import { html } from "htm/preact";

import { ApplicationIcons } from "../appearance/Icons.mjs";

import { MessageContent } from "./MessageContent.mjs";
import { ExpandablePanel } from "./ExpandablePanel.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";
import { resolveToolInput, ToolCallView } from "./Tools.mjs";
import { VirtualList } from "./VirtualList.mjs";
import { MarkdownDiv } from "./MarkdownDiv.mjs";

/**
 * Renders the ChatViewVirtualList component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the chat view.
 * @param {import("../types/log").Messages} props.messages - The array of chat messages.
 * @param {"compact" | "complete"} [props.toolCallStyle] - Whether to show tool calls
 * @param {Object} [props.style] - Inline styles for the chat view.
 * @param {boolean} props.indented - Whether the chatview has indented messages
 * @param {boolean} [props.numbered] - Whether the chatview is numbered
 * @param {import("htm/preact").MutableRef<HTMLElement>} props.scrollRef - The scrollable parent element
 * @returns {import("preact").JSX.Element} The component.
 */
export const ChatViewVirtualList = ({
  id,
  messages,
  toolCallStyle,
  style,
  indented,
  numbered = true,
  scrollRef,
}) => {
  const collapsedMessages = resolveMessages(messages);

  const renderRow = (item, index) => {
    const number =
      collapsedMessages.length > 1 && numbered ? index + 1 : undefined;
    return html`<${ChatMessageRow}
      id=${id}
      number=${number}
      resolvedMessage=${item}
      indented=${indented}
      toolCallStyle=${toolCallStyle}
    />`;
  };

  const result = html`<${VirtualList}
    data=${collapsedMessages}
    tabIndex="0"
    renderRow=${renderRow}
    scrollRef=${scrollRef}
    style=${{ width: "100%", marginTop: "1em", ...style }}
  />`;

  return result;
};

/**
 * Renders the ChatView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the chat view.
 * @param {import("../types/log").Messages} props.messages - The array of chat messages.
 * @param {"compact" | "complete"} [props.toolCallStyle] - Whether to show tool calls
 * @param {Object} [props.style] - Inline styles for the chat view.
 * @param {boolean} props.indented - Whether the chatview has indented messages
 * @param {boolean} [props.numbered] - Whether the chatview is numbered
 * @returns {import("preact").JSX.Element} The component.
 */
export const ChatView = ({
  id,
  messages,
  toolCallStyle,
  style,
  indented,
  numbered = true,
}) => {
  const collapsedMessages = resolveMessages(messages);
  const result = html` <div style=${style}>
    ${collapsedMessages.map((msg, index) => {
      const number =
        collapsedMessages.length > 1 && numbered ? index + 1 : undefined;
      return html`<${ChatMessageRow}
        id=${id}
        number=${number}
        resolvedMessage=${msg}
        indented=${indented}
        toolCallStyle=${toolCallStyle}
      />`;
    })}
  </div>`;
  return result;
};

/**
 * Renders the ChatMessage component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.id - The ID for the chat view.
 * @param {number} [props.number] - The message number
 * @param {ResolvedMessage} props.resolvedMessage - The array of chat messages.
 * @param {"compact" | "complete"} [props.toolCallStyle] - Whether to show tool calls
 * @param {boolean} props.indented - Whether the chatview has indented messages
 * @returns {import("preact").JSX.Element} The component.
 */
export const ChatMessageRow = ({
  id,
  number,
  resolvedMessage,
  toolCallStyle,
  indented,
}) => {
  if (number) {
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
        ${number}
      </div>
      <${ChatMessage}
        id=${`${id}-chat-messages`}
        message=${resolvedMessage.message}
        toolMessages=${resolvedMessage.toolMessages}
        indented=${indented}
        toolCallStyle=${toolCallStyle}
      />
    </div>`;
  } else {
    return html`<${ChatMessage}
      id=${`${id}-chat-messages`}
      message=${resolvedMessage.message}
      toolMessages=${resolvedMessage.toolMessages}
      indented=${indented}
      toolCallStyle=${toolCallStyle}
    />`;
  }
};

/**
 * @typedef {Object} ResolvedMessage
 * @property {import("../types/log").ChatMessageAssistant | import("../types/log").ChatMessageSystem | import("../types/log").ChatMessageUser} message - The main chat message.
 * @property {import("../types/log").ChatMessageTool[]} [toolMessages] - Optional array of tool-related messages.
 */

/**
 * Renders the ChatView component.
 *
 * @param {import("../types/log").Messages} messages - The array of chat messages.
 * @returns {ResolvedMessage[]} The component.
 */
export const resolveMessages = (messages) => {
  // Filter tool messages into a sidelist that the chat stream
  // can use to lookup the tool responses

  /**
   * @type {Array<{message: import("../types/log").ChatMessageAssistant | import("../types/log").ChatMessageSystem | import("../types/log").ChatMessageUser, toolMessages?: import("../types/log").ChatMessageTool[]}>}
   */
  const resolvedMessages = [];
  for (const message of messages) {
    if (message.role === "tool") {
      // Add this tool message onto the previous message
      if (resolvedMessages.length > 0) {
        const msg = resolvedMessages[resolvedMessages.length - 1];
        msg.toolMessages.push(message);
      }
    } else {
      resolvedMessages.push({ message, toolMessages: [] });
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
  return collapsedMessages;
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

/**
 *
 * @param {Object} props
 * @param {string} props.id - The ID for the chat view.
 * @param {import("../types/log").ChatMessageAssistant | import("../types/log").ChatMessageSystem | import("../types/log").ChatMessageUser} props.message - The primary message
 * @param {import("../types/log").ChatMessageTool[]} props.toolMessages - The tool output message
 * @param {boolean} props.indented - Whether the chatview has indented messages
 * @param {"compact" | "complete"} props.toolCallStyle - Whether to hide tool calls
 * @returns {import("preact").JSX.Element} The component.
 */
const ChatMessage = ({
  id,
  message,
  toolMessages,
  indented,
  toolCallStyle,
}) => {
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
      
      ${
        message.role === "assistant" && message.reasoning
          ? html` <div
              style=${{
                marginLeft: indented ? "1.1rem" : "0",
                paddingBottom: "0.8rem",
              }}
            >
              <div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>Reasoning</div>
              <${ExpandablePanel} collapse=${true}><${MarkdownDiv} markdown=${message.reasoning}/></${ExpandablePanel}>
            </div>`
          : undefined
      }

      <div style=${{ marginLeft: indented ? "1.1rem" : "0", paddingBottom: indented ? "0.8rem" : "0" }}>
      ${
        message.role === "assistant" && message.reasoning
          ? html`<div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>
              Response
            </div>`
          : ""
      }
      <${ExpandablePanel} collapse=${collapse}>
        <${MessageContents}
          key=${`${id}-contents`}
          message=${message}
          toolMessages=${toolMessages}
          toolCallStyle=${toolCallStyle}
        />
      </${ExpandablePanel}>
      </div>
    </div>
  `;
};

/**
 *
 * @param {Object} props
 * @param {import("../types/log").ChatMessageAssistant | import("../types/log").ChatMessageSystem | import("../types/log").ChatMessageUser} props.message - The primary message
 * @param {import("../types/log").ChatMessageTool[]} props.toolMessages - The tool output message
 * @param {"compact" | "complete"} props.toolCallStyle - Whether to hide tool calls
 * @returns {import("preact").JSX.Element | import("preact").JSX.Element[]} The component.
 */
const MessageContents = ({ message, toolMessages, toolCallStyle }) => {
  if (
    message.role === "assistant" &&
    message.tool_calls &&
    message.tool_calls.length
  ) {
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
        return html`<code>tool: ${functionCall}</code>`;
      } else {
        return html`<${ToolCallView}
          functionCall=${functionCall}
          input=${input}
          inputType=${inputType}
          output=${resolvedToolOutput}
        />`;
      }
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

/**
 *
 * @param {import("../types/log").ChatMessageTool} toolMessage - The tool output message
 * @returns {Array<{type: string, content: import("../types/log").Content4}>|undefined} An array of formatted tool message objects, or undefined if toolMessage is falsy.
 */
const resolveToolMessage = (toolMessage) => {
  if (!toolMessage) {
    return undefined;
  }

  const content =
    toolMessage.error !== null && toolMessage.error
      ? toolMessage.error.message
      : toolMessage.content;
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
