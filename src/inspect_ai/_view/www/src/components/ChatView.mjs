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
 * @returns {import("preact").JSX.Element} The component.
 */
export const ChatView = ({ id, messages, style }) => {
  // Filter tool messages into a sidelist that the chat stream
  // can use to lookup the tool responses
  const toolMessages = {};
  const nonToolMessages = [];
  for (const message of messages) {
    if (message.role === "tool") {
      toolMessages[message.tool_call_id] = message;
    } else {
      nonToolMessages.push(message);
    }
  }

  // Capture system messages (there could be multiple)
  const systemMessages = [];
  const collapsedMessages = nonToolMessages
    .map((msg) => {
      if (msg.role === "system") {
        systemMessages.push(msg);
      }
      return msg;
    })
    .filter((msg) => {
      return msg.role !== "system";
    });

  // Collapse system messages
  const systemMessage = systemMessages.reduce(
    (reduced, message) => {
      const systemContents = Array.isArray(message.content)
        ? message.content
        : [message.content];
      reduced.content.push(...systemContents.map(normalizeContent));
      return reduced;
    },
    { role: "system", content: [] },
  );

  // Converge them
  if (systemMessage && systemMessage.content.length > 0) {
    collapsedMessages.unshift(systemMessage);
  }

  const result = html`
    <div style=${style}>
      ${collapsedMessages.map((msg) => {
        return html`<${ChatMessage}
          id=${`${id}-chat-messages`}
          message=${msg}
          toolMessages=${toolMessages}
        />`;
      })}
    </div>
  `;

  return result;
};

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

const ChatMessage = ({ id, message, toolMessages }) => {
  const iconCls = iconForMsg(message);
  const icon = iconCls ? html`<i class="${iconCls}"></i>` : "";
  const collapse = message.role === "system";
  return html`
    <div
      class="container-fluid ${message.role}"
      style=${{
        fontSize: FontSize.base,
        fontWeight: "300",
        paddingBottom: ".5em",
        justifyContent: "flex-start",
        marginLeft: "0",
        marginRight: "0",
        opacity: message.role === "system" ? "0.7" : "1",
        whiteSpace: "normal",
      }}
    >
      <div class="row row-cols-2">
        <div
          class="col"
          style=${{
            flex: "0 1 1em",
            paddingLeft: "0",
            paddingRight: "0.5em",
            marginLeft: "0",
            fontWeight: "500",
          }}
        >
          ${icon}
        </div>
        <div
          class="col"
          style=${{
            flex: "1 0 auto",
            marginLeft: ".3rem",
            paddingLeft: "0",
          }}
        >
          <div style=${{ fontWeight: "500", ...TextStyle.label }}>${message.role}</div>
          <${ExpandablePanel} collapse=${collapse}>
            <${MessageContents}
              key=${`${id}-contents`}
              message=${message}
              toolMessages=${toolMessages}
            />
          </${ExpandablePanel}>
        </div>
      </div>
    </div>
  `;
};

const MessageContents = ({ message, toolMessages }) => {
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
      // Get the basic tool data
      const toolMessage = toolMessages[tool_call.id];

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
  let iconCls = ApplicationIcons.role.assistant;
  if (msg.role === "user") {
    iconCls = ApplicationIcons.role.user;
  } else if (msg.role === "system") {
    iconCls = ApplicationIcons.role.system;
  } else if (msg.role === "tool") {
    iconCls = ApplicationIcons.role.tool;
  }
  return iconCls;
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
        text: content,
      },
    ];
  } else {
    return content.map((con) => {
      if (typeof content === "string") {
        return {
          type: "tool",
          text: content,
        };
      } else if (con.type === "text") {
        return {
          ...con,
          type: "tool",
        };
      }
    });
  }
};
