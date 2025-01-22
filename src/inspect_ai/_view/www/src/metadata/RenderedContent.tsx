import { ApplicationIcons } from "../appearance/icons";

import React from "preact/compat";
import { ANSIDisplay } from "../components/AnsiDisplay";
import { ChatMessageRenderer } from "../samples/chat/ChatMessageRenderer";
import { formatNumber } from "../utils/format";
import { MetaDataView } from "./MetaDataView";

import clsx from "clsx";
import styles from "./RenderedContent.module.css";
import { Buckets, ContentRenderer } from "./Types";

interface RenderedContentProps {
  id: string;
  entry: { name: string; value: unknown };
}

/**
 * Renders content based on its type using registered content renderers.
 */
export const RenderedContent: React.FC<RenderedContentProps> = ({
  id,
  entry,
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

  if (renderer) {
    const { rendered } = renderer.render(id, entry);
    if (rendered !== undefined) {
      return rendered;
    } else {
      return entry.value;
    }
  } else {
    return entry.value;
  }
};

/**
 * Object containing different content renderers.
 * Each renderer is responsible for rendering a specific type of content.
 */
const contentRenderers: Record<string, ContentRenderer> = {
  AnsiString: {
    bucket: Buckets.first,
    canRender: (entry) => {
      return (
        typeof entry.value === "string" && entry.value.indexOf("\u001b") > -1
      );
    },
    render: (_id, entry) => {
      return {
        rendered: <ANSIDisplay output={entry.value} />,
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
        rendered: (
          <React.Fragment>
            <i class={ApplicationIcons.model} /> {entry.value._model}
          </React.Fragment>
        ),
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
    render: (_id, entry) => {
      const rendered = entry.value.trim();
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
          entry.value.map((e: unknown) => {
            return typeof e;
          }),
        );
        return types.size === 1;
      } else {
        return false;
      }
    },
    render: (id, entry) => {
      const arrayMap: Record<string, unknown> = {};
      entry.value.forEach((e: unknown, index: number) => {
        arrayMap[`[${index}]`] = e;
      });

      const arrayRendered = (
        <MetaDataView
          id={id}
          className={"font-size-small"}
          entries={arrayMap}
          tableOptions="borderless,sm"
          compact={true}
        />
      );
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
      const results: React.ReactNode[] = [];
      results.push(
        <div className={styles.query}>
          <i class={ApplicationIcons.search}></i> {entry.value.query}
        </div>,
      );
      entry.value.results.forEach(
        (result: { url: string; summary: string }) => {
          results.push(
            <div>
              <a href={result.url}>{result.url}</a>
            </div>,
          );
          results.push(
            <div className={clsx("text-size-smaller", styles.summary)}>
              {result.summary}
            </div>,
          );
        },
      );
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
        rendered: <pre className={styles.preWrap}>{entry.value}</pre>,
      };
    },
  },
  Html: {
    bucket: Buckets.intermediate,
    canRender: (entry) => {
      return typeof entry.value === "object" && entry.value._html;
    },
    render: (_id, entry) => {
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
    render: (_id, entry) => {
      return {
        rendered: <img src={entry.value} />,
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
        rendered: (
          <MetaDataView
            id={id}
            className={"text-size-smaller"}
            entries={entry.value}
            tableOptions="borderless,sm"
            compact
          />
        ),
      };
    },
  },
};
