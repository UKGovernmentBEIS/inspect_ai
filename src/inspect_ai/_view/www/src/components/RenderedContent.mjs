import { html } from "htm/preact";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

import { ANSIDisplay } from "./AnsiDisplay.mjs";
import { MetaDataView } from "./MetaDataView.mjs";
import { ChatView } from "./ChatView.mjs";
import { formatNumber } from "../utils/Format.mjs";

export const RenderedContent = ({
  id,
  entry,
  context,
  defaultRendering,
  options,
}) => {
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
    const { rendered, afterBody } = renderer.render(
      id,
      entry,
      defaultRendering,
      options,
      context,
    );
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
        rendered: html`<i class="${ApplicationIcons.model}"></i> ${entry.value
            ._model}`,
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
    render: (id, entry, _defaultRendering, _options, context) => {
      const arrayMap = {};
      entry.value.forEach((entry, index) => {
        arrayMap[`[${index}]`] = entry;
      });

      const arrayRendered = html`<${MetaDataView}
        id=${id}
        style=${{ fontSize: FontSize.small }}
        entries="${arrayMap}"
        tableOptions="borderless,sm"
        context=${context}
        compact
      />`;
      return { rendered: arrayRendered };
    },
  },
  ChatMessage: {
    bucket: Buckets.first,
    canRender: (entry) => {
      const val = entry.value;
      return (
        Array.isArray(val) &&
        val.length > 0 &&
        val[0]?.role !== undefined &&
        val[0]?.content !== undefined
      );
    },
    render: (_id, entry) => {
      return {
        rendered: html`<${ChatView} messages=${entry.value} />`,
      };
    },
  },
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
  Object: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object";
    },
    render: (id, entry, _defaultRendering, _options, context) => {
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
          context=${context}
          compact
        />`,
      };
    },
  },
};
