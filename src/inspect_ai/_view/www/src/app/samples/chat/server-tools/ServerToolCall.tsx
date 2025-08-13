import { FC, ReactNode } from "react";
import { ContentToolUse } from "../../../../@types/log";

import clsx from "clsx";
import ExpandablePanel from "../../../../components/ExpandablePanel";
import { ApplicationIcons } from "../../../appearance/icons";
import { RecordTree } from "../../../content/RecordTree";
import { RenderedContent } from "../../../content/RenderedContent";
import styles from "./ServerToolCall.module.css";

interface ServerToolCallProps {
  id?: string;
  content: ContentToolUse;
}

/**
 * Renders the ToolOutput component.
 */
export const ServerToolCall: FC<ServerToolCallProps> = ({ id, content }) => {
  return <McpToolUse id={id} content={content} />;
};

const McpToolUse: FC<ServerToolCallProps> = ({ id, content }) => {
  const args =
    typeof content.arguments === "object"
      ? content.arguments
      : { arguments: content.arguments };

  const record: Record<string, unknown> = {
    ...args,
  };

  const titleStr = content.context
    ? `${content.context} — ${content.name}()`
    : `${content.name}()`;

  return (
    <div id={id} className={clsx(styles.mcpToolUse)}>
      <div
        className={clsx(
          styles.title,
          "text-size-small",
          "text-style-secondary",
        )}
      >
        <i className={ApplicationIcons.role.tool} />
        <pre className={styles.titleText}>{titleStr}</pre>
        <div className={styles.type}>{content.type}</div>
      </div>

      <div className={styles.args}>
        {Object.keys(record).map((key, index) => {
          const value = record[key];

          let valueRecord: Record<string, unknown> | undefined = undefined;
          if (Array.isArray(value)) {
            valueRecord = {};
            for (var i = 0; i < value.length; i++) {
              valueRecord[`[${i}]`] = value[i];
            }
          } else if (value && typeof value === "object") {
            valueRecord = value as Record<string, unknown>;
          }

          return (
            <>
              <LabelDiv label={key} />
              {valueRecord ? (
                <RecordTree id={`${id}-val-${index}`} record={valueRecord} />
              ) : (
                <ValueDiv>{value as ReactNode}</ValueDiv>
              )}
            </>
          );
        })}

        {isWebSearchResult(content) ? (
          <>
            <LabelDiv label={"results"} />
            <ValueDiv>
              {(content.result as WebResult[]).map((result, index) => (
                <div key={index} className={styles.result}>
                  <a
                    href={result.url}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {result.title}
                  </a>
                </div>
              ))}
            </ValueDiv>
          </>
        ) : undefined}
      </div>

      {content.error ? (
        <div className={styles.error}>
          <span>Error: {content.error}</span>
        </div>
      ) : !isWebSearchResult(content) ? (
        <ExpandablePanel id={`${id}-output`} collapse={true}>
          <RenderedContent
            id={`${id}-output`}
            entry={{ name: "Output", value: content.result }}
            renderOptions={{ renderString: "markdown" }}
          />
        </ExpandablePanel>
      ) : undefined}
    </div>
  );
};

const isWebSearchResult = (
  content: ContentToolUse,
): content is ContentToolUse & { result: WebResult[] } => {
  return (
    content.name === "web_search" &&
    Array.isArray(content.result) &&
    content.result.every(
      (item) =>
        typeof item === "object" &&
        "title" in item &&
        "url" in item &&
        "type" in item,
    )
  );
};

const LabelDiv: FC<{ label: string }> = ({ label }) => {
  return (
    <div
      className={clsx(
        styles.argLabel,
        "text-style-secondary",
        "text-size-smaller",
      )}
    >
      <pre>{label}</pre>
    </div>
  );
};

const ValueDiv: FC<{ children: ReactNode }> = ({ children }) => {
  return <div className={clsx("text-size-smaller")}>{children}</div>;
};

interface WebResult {
  title: string;
  url: string;
  type: string;
}
