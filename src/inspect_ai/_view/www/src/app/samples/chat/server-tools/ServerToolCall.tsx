import { FC, ReactNode } from "react";
import { ContentToolUse } from "../../../../@types/log";

import clsx from "clsx";
import { ApplicationIcons } from "../../../appearance/icons";
import { RenderedContent } from "../../../content/RenderedContent";
import styles from "./ServerToolCall.module.css";
import { RecordTree } from "../../../content/RecordTree";
import ExpandablePanel from "../../../../components/ExpandablePanel";

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
              <div
                className={clsx(
                  styles.argLabel,
                  "text-style-secondary",
                  "text-size-smaller",
                )}
              >
                <pre>{key}</pre>
              </div>
              {valueRecord ? (
                <RecordTree id={`${id}-val-${index}`} record={valueRecord} />
              ) : (
                <div className={clsx("text-size-smaller")}>
                  {value as ReactNode}
                </div>
              )}
            </>
          );
        })}
      </div>

      {content.error ? (
        <div className={styles.error}>
          <span>Error: {content.error}</span>
        </div>
      ) : (
        <ExpandablePanel id={`${id}-output`} collapse={true}>
          <RenderedContent
            id={`${id}-output`}
            entry={{ name: "Output", value: content.result }}
            renderOptions={{ renderString: "markdown" }}
          />
        </ExpandablePanel>
      )}
    </div>
  );
};
