import { html } from "htm/preact";

import { icons, sharedStyles } from "../Constants.mjs";

import { iconForMsg, ChatView } from "./ChatView.mjs";
import { DialogButton, DialogAfterBody } from "./Dialog.mjs";
import { ANSIDisplay } from "./AnsiDisplay.mjs";


export const RenderedContent = ({ id, entry, context, defaultRendering, options }) => {
  if (entry.value === null) {
    return "[null]";
  }

  const renderer = Object.keys(contentRenderers)
    .map((key) => {
      return contentRenderers[key];
    })
    .sort((a, b) => {
      return a.bucket - b.bucket;
    })
    .find((renderer) => {
      return renderer.canRender(entry);
    });

  let value = entry.value;
  if (renderer) {
    const { rendered, afterBody } = renderer.render(id, entry, defaultRendering, options);
    if (rendered !== undefined) {
      value = rendered;
      if (afterBody !== undefined) {
        context.afterBody(afterBody);
      }
    }
  }
  return html`${value}`;
};

const Buckets = {
  first: 0,
  intermediate: 10,
  final: 1000,
};

const contentRenderers = {
  AnsiString: {
    bucket: Buckets.first,
    canRender: (entry) => {
      return (
        typeof entry.value === "string" && entry.value.indexOf("\u001b") > -1
      );
    },
    render: (id, entry) => {
      return {
        rendered: html`<${ANSIDisplay} output=${entry.value} />`,
      };
    },
  },
  Model: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.value._model;
    },
    render: (_id, entry) => {
      return {
        rendered: html`<i class="${icons.model}"></i> ${entry.value._model}`,
      };
    },
  },
  Boolean: {
    order: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "boolean";
    },
    render: (id, entry) => {
      entry.value = entry.value.toString();
      return contentRenderers.String.render(id, entry);
    },
  },
  Number: { 
    order: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "number";
    },
    render: (id, entry) => {
      entry.value = entry.value.toString();
      return contentRenderers.String.render(id, entry);
    },
  },
  String: {
    bucket: Buckets.final,
    canRender: (entry) => {
      return typeof entry.value === "string";
    },
    render: (_id, entry, defaultRendering) => {
      const rendered = defaultRendering ? defaultRendering(entry.value.trim()) : entry.value.trim();
      return {
        rendered,
      };
    },
  },
  Array: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      const isArray = Array.isArray(entry.value);
      if (isArray) {
        const types = new Set(
          entry.value.map((entry) => {
            return typeof entry;
          })
        );
        return types.length === 1;
      } else {
        return false;
      }
    },
    render: (_id, entry) => {
      entry.value = `[${entry.value.join(",")}]`
      return contentRenderers.String.render(id, entry);
    },
  },
  ChatMessage: {
    bucket: Buckets.first,
    canRender: (entry) => {
      const val = entry.value;
      return (
        Array.isArray(val) &&
        val.length > 0 &&
        val[0].role !== undefined &&
        val[0].content !== undefined
      );
    },
    render: (id, entry, defaultRendering, options) => {
      if (options.expanded) {
        return { 
          rendered: html`<${ChatView} messages=${entry.value}/>`
        }
      } else {
        // Read the first chat message
        const previewMsg = entry.value[0];
        const preview = previewMsg.content;
        const icon = iconForMsg(previewMsg);

        return {
          rendered: html`
            <${ContentWithMoreButton} id=${id} icon=${icon} content=${preview} />
          `,
          afterBody: html`<${DialogAfterBody}
            id=${id}
            title=${entry.name}
            centered=true
            scrollable=true
            classes="chat-modal"
          >
            <${ChatView} messages=${entry.value}/>
          </${DialogAfterBody}>`,
        };  
      }
    },
  },
  web_search: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.name === "web_search";
    },
    render: (id, entry) => {
      const results = [];
      results.push(
        html`<div style=${{ marginBottom: "0.5rem", fontWeight: "500" }}>
          <i class=${icons.search}></i> ${entry.value.query}
        </div>`
      );
      entry.value.results.forEach((result) => {
        results.push(
          html`<div>
            <a href="${result.url}">${result.url}</a>
          </div>`
        );
        results.push(
          html`<div style=${{ fontSize: "0.7rem", marginBottom: "0.5rem" }}>
            ${result.summary}
          </div>`
        );
      });
      return {
        rendered: results,
      };
    },
  },
  Html: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.value._html;
    },
    render: (id, entry) => {
      return {
        rendered: entry.value._html,
      };
    },
  },
  Object: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object";
    },
    render: (id, entry) => {
      // Generate a json preview
      const summary = [];
      const keys = Object.keys(entry.value);
      if (keys.length > 4) {
        summary.push(...keys.slice(0, 2));
        summary.push("...");
        summary.push(...keys.slice(keys.length - 2));
      } else {
        summary.push(...keys);
      }

      const preview = `{${summary.join(", ")}}`;
      const highlightedHtml = Prism.highlight(
        JSON.stringify(entry.value, null, 2),
        Prism.languages.javascript,
        "javacript"
      );

      return {
        rendered: html`<${ContentWithMoreButton}
          id=${id}
          icon=${icons.json}
          content=${preview}
        />`,
        afterBody: html`<${DialogAfterBody}
            id=${id}
            title=${entry.name}
            centered=true
            scrollable=true
            style=${{
              fontSize: "0.8em",
              maxWidth: "650px",
            }}
          >
            <pre><code class="sourceCode" dangerouslySetInnerHTML="${{
              __html: DOMPurify.sanitize(highlightedHtml),
            }}">
            </code></pre>
          </${DialogAfterBody}>`,
      };
    },
  },
};

const ContentWithMoreButton = ({ id, icon, content }) => {
  return html`<div><i class="${icon}"></i><span style=${{
    fontSize: "0.7rem",
    marginLeft: "0.5rem",
    marginRight: "0.5rem",
  }}>${content}</span>
            <${DialogButton} id=${id} style=${
    sharedStyles.moreButton
  } btnType="btn">
              <i class="${icons.more}"></i>
            </${DialogButton}>
        </div>`;
};
