import { html } from "htm/preact";

import { icons } from "../Constants.mjs";

import { MessageContent } from "./MessageContent.mjs";

// role
// content
export const ChatView = ({ messages, style }) => {
  // Filter tool messages into a sidelist that the chat stream
  // can use to lookup the tool responses
  const toolMessages = {};
  const nonToolMessages = messages
    .map((msg) => {
      if (msg.role === "tool") {
        toolMessages[msg.tool_call_id] = msg;
      }
      return msg;
    })
    .filter((msg) => {
      return msg.role !== "tool";
    });

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
  const systemMessage = systemMessages.reduce((reduced, message) => {
    const systemContents = Array.isArray(message.content)
      ? message.content
      : [message.content];
    reduced.content.push(...systemContents.map(normalizeContent));
    return reduced;
  }, { role: "system", content: []});

  // Converge them
  if (systemMessage && systemMessage.content.length > 0) {
    collapsedMessages.unshift(systemMessage);
  }

  return html`
    <div style=${{ paddingTop: "0.5em", ...style }}>
      ${collapsedMessages.map((msg) => {
        return html`<${ChatMessage}
          message=${msg}
          toolMessages=${toolMessages}
        />`;
      })}
    </div>
  `;
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

const ChatMessage = ({ message, toolMessages }) => {
  const iconCls = iconForMsg(message);
  const icon = iconCls ? html`<i class="${iconCls}"></i>` : "";

  return html`
    <div
      class="container-fluid ${message.role}"
      style=${{
        fontSize: "0.9rem",
        fontWeight: "300",
        paddingBottom: ".5em",
        justifyContent: "flex-start",
        marginLeft: "0",
        marginRight: "0",
        opacity: message.role === "system" ? "0.7" : "1",
        whiteSpace: "normal"
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
          <div style=${{ fontWeight: "500" }}>${message.role}</div>
          <div style=${{ fontSize: "0.8rem" }}>
            <${MessageContents}
              message=${message}
              toolMessages=${toolMessages}
            />
          </div>
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
        </div>`
      );
    }

    // Render the tool calls made by this message
    const toolCalls = message.tool_calls.map((tool_call) => {
      const toolMessage = toolMessages[tool_call.id];
      const fn = tool_call.function;
      const args = tool_call.arguments
        ? Object.keys(tool_call.arguments).map((key) => {
            return `${key}: ${tool_call.arguments[key]}`;
          })
        : [];

      const adaptToolMessage = (toolMessage) => {
        if (!toolMessage) {
          return undefined;
        }

        const content = toolMessage.content;
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
      const adaptedToolMessage = adaptToolMessage(toolMessage);
      return html`<p>
        <i class="bi bi-tools" style=${{
          marginRight: "0.2rem",
          opacity: "0.4",
        }}></i>
        <code style=${{ fontSize: "0.7rem" }}>${fn}(${args.join(",")})</code>
        <div>
          ${
            toolMessage
              ? html`<${MessageContent} contents=${adaptedToolMessage} />`
              : ""
          }
        </div>
        </p>`;
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
  let iconCls = icons.role.assistant;
  if (msg.role === "user") {
    iconCls = icons.role.user;
  } else if (msg.role === "system") {
    iconCls = icons.role.system;
  } else if (msg.role === "tool") {
    iconCls = icons.role.tool;
  }
  return iconCls;
};
