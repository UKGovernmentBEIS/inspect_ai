import { html } from "htm/preact";

import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";

import { ANSIDisplay } from "../AnsiDisplay.mjs";
import { MetaDataView } from "../MetaDataView.mjs";
import { ChatMessageRenderer } from "./ChatMessageRenderer.mjs";
import { formatNumber } from "../../utils/Format.mjs";
import { Buckets } from "./Types.mjs";

/**
 * Renders content based on its type using registered content renderers.
 *
 * @param {Object} props - Properties passed to the component.
 * @param {string} props.id - Unique identifier for the rendered content.
 * @param {Object} props.entry - Entry object containing `value` to be rendered.
 * @returns {import("preact").JSX.Element | string} Rendered content.
 */
export const RenderedContent = ({ id, entry }) => {
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
    const { rendered } = renderer.render(id, entry);
    if (rendered !== undefined) {
      value = rendered;
    }
  }
  return html`${value}`;
};

/**
 * Object containing different content renderers.
 * Each renderer is responsible for rendering a specific type of content.
 *
 * @type {Record<string, import("./Types.mjs").ContentRenderer>}
 */
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
        rendered: html`<i class="${ApplicationIcons.model}"></i> ${entry.value
            ._model}`,
      };
    },
  },
  Boolean: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "boolean";
    },
    render: (id, entry) => {
      entry.value = entry.value.toString();
      return contentRenderers.String.render(id, entry);
    },
  },
  Number: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "number";
    },
    render: (id, entry) => {
      entry.value = formatNumber(entry.value);
      return contentRenderers.String.render(id, entry);
    },
  },
  String: {
    bucket: Buckets.final,
    canRender: (entry) => {
      return typeof entry.value === "string";
    },
    render: (_id, entry, defaultRendering) => {
      const rendered = defaultRendering
        ? defaultRendering(entry.value.trim())
        : entry.value.trim();
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
          }),
        );
        return types.size === 1;
      } else {
        return false;
      }
    },
    render: (id, entry) => {
      const arrayMap = {};
      entry.value.forEach((entry, index) => {
        arrayMap[`[${index}]`] = entry;
      });

      const arrayRendered = html`<${MetaDataView}
        id=${id}
        style=${{ fontSize: FontSize.small }}
        entries="${arrayMap}"
        tableOptions="borderless,sm"
        compact
      />`;
      return { rendered: arrayRendered };
    },
  },
  ChatMessage: ChatMessageRenderer,
  web_search: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.name === "web_search";
    },
    render: (_id, entry) => {
      const results = [];
      results.push(
        html`<div style=${{ marginBottom: "0.5rem", fontWeight: "500" }}>
          <i class=${ApplicationIcons.search}></i> ${entry.value.query}
        </div>`,
      );
      entry.value.results.forEach((result) => {
        results.push(
          html`<div>
            <a href="${result.url}">${result.url}</a>
          </div>`,
        );
        results.push(
          html`<div
            style=${{ fontSize: FontSize.smaller, marginBottom: "0.5rem" }}
          >
            ${result.summary}
          </div>`,
        );
      });
      return {
        rendered: results,
      };
    },
  },
  web_browser: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return (
        typeof entry.value === "string" && entry.name?.startsWith("web_browser")
      );
    },
    render: (_id, entry) => {
      return {
        rendered: html`<pre style=${{ whiteSpace: "pre-wrap" }}>
${entry.value}</pre
        >`,
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
  Image: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return (
        typeof entry.value === "string" && entry.value.startsWith("data:image/")
      );
    },
    render: (id, entry) => {
      return {
        rendered: html`<img src=${entry.value} />`,
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

      return {
        rendered: html`<${MetaDataView}
          id=${id}
          style=${{ fontSize: FontSize.smaller }}
          entries="${entry.value}"
          tableOptions="borderless,sm"
          compact
        />`,
      };
    },
  },
};
