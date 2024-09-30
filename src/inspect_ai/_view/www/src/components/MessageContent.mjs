import { html } from "htm/preact";
import { MarkdownDiv } from "./MarkdownDiv.mjs";
import { ToolOutput } from "./Tools.mjs";

export const MessageContent = (props) => {
  const { contents } = props;
  if (Array.isArray(contents)) {
    return contents.map((content, index) => {
      if (typeof content === "string") {
        return messageRenderers["text"].render({
          text: content,
          index: index === contents.length - 1,
        });
      } else {
        if (content) {
          const renderer = messageRenderers[content.type];
          if (renderer) {
            return renderer.render(content, index === contents.length - 1);
          } else {
            console.error(`Unknown message content type '${content.type}'`);
          }
        }
      }
    });
  } else {
    // This is a simple string
    return messageRenderers["text"].render({ text: contents });
  }
};

// TODO: We should setting overflow scrolling here
// don't break-all
const messageRenderers = {
  text: {
    render: (content, isLast) => {
      return html`<${MarkdownDiv}
        markdown=${content.text}
        class=${isLast ? "no-last-para-padding" : ""}
      />`;
    },
  },
  image: {
    render: (content) => {
      if (content.image.startsWith("data:")) {
        return html`<img
          src="${content.image}"
          style=${{
            maxWidth: "400px",
            border: "solid var(--bs-border-color) 1px",
          }}
        />`;
      } else {
        return html`<code>${content.image}</code>`;
      }
    },
  },
  tool: {
    render: (content) => {
      return html`<${ToolOutput} output=${content.content} />`;
    },
  },
};
