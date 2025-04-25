import JSON5 from "json5";
import { ApplicationIcons } from "../appearance/icons";

import { ChatMessageRenderer } from "../../app/samples/chat/ChatMessageRenderer";
import { ANSIDisplay } from "../../components/AnsiDisplay";
import { formatNumber } from "../../utils/format";
import { MetaDataView } from "./MetaDataView";

import clsx from "clsx";
import { FC, Fragment, isValidElement, JSX, ReactNode } from "react";
import JSONPanel from "../../components/JsonPanel";
import { isJson } from "../../utils/json";
import styles from "./RenderedContent.module.css";
import { Buckets, ContentRenderer } from "./types";

interface RenderedContentProps {
  id: string;
  entry: { name: string; value: unknown };
}

/**
 * Renders content based on its type using registered content renderers.
 */
export const RenderedContent: FC<RenderedContentProps> = ({
  id,
  entry,
}): JSX.Element => {
  // Explicitly specify return type
  if (entry.value === null) {
    return <span>[null]</span>;
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
    if (rendered !== undefined && isValidElement(rendered)) {
      return rendered;
    }
  }

  // Safely convert any value to a string representation
  const displayValue = (() => {
    try {
      if (typeof entry.value === "object") {
        return JSON.stringify(entry.value);
      }
      return String(entry.value).trim();
    } catch (e) {
      return "[Unable to display value]";
    }
  })();

  return <span>{displayValue}</span>;
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
  JsonString: {
    bucket: Buckets.first,
    canRender: (entry) => {
      if (typeof entry.value === "string") {
        const trimmed = entry.value.trim();
        return isJson(trimmed);
      }
      return false;
    },
    render: (_id, entry) => {
      const obj = JSON5.parse(entry.value);
      return { rendered: <JSONPanel data={obj as Record<string, unknown>} /> };
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
          <Fragment>
            <i className={ApplicationIcons.model} /> {entry.value._model}
          </Fragment>
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
        if (entry.value.length === 0 || entry.value.length === 1) {
          return true;
        }
        const types = new Set(
          entry.value
            .filter((e: unknown) => e !== null)
            .map((e: unknown) => {
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
      const results: ReactNode[] = [];
      results.push(
        <div className={styles.query}>
          <i className={ApplicationIcons.search}></i> {entry.value.query}
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
