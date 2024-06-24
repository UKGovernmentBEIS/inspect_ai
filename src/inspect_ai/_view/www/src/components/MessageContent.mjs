import { html } from "htm/preact";
import { MarkdownDiv } from "./MarkdownDiv.mjs";

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
        const renderer = messageRenderers[content.type];
        if (renderer) {
          return renderer.render(content, index === contents.length - 1);
        } else {
          console.error(`Unknown message content type '${content.type}'`);
        }
      }
    });
  } else {
    // This is a simple string
    return messageRenderers["text"].render({ text: contents });
  }
};

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
      return html`<img
        src="${content.image}"
        style=${{
          maxWidth: "400px",
          border: "solid var(--bs-border-color) 1px",
        }}
      />`;
    },
  },
  tool: {
    render: (content) => {
      return html`<pre
        style=${{
          marginLeft: "2px",
          padding: "0.5em 0.5em 0.5em 0.5em",
          whiteSpace: "pre-wrap",
          marginBottom: "0",
        }}
      ><code class="sourceCode" style=${{ wordWrap: "anywhere" }}>
      ${content.text}
      </code></pre>`;
    },
  },
};
