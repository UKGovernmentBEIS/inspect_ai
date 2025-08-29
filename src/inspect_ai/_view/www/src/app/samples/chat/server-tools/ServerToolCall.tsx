import { FC, ReactNode } from "react";
import { ContentToolUse } from "../../../../@types/log";

import clsx from "clsx";
import ExpandablePanel from "../../../../components/ExpandablePanel";
import { asJsonObjArray, isJson } from "../../../../utils/json";
import { ApplicationIcons } from "../../../appearance/icons";
import { RecordTree } from "../../../content/RecordTree";
import { RenderedContent } from "../../../content/RenderedContent";
import styles from "./ServerToolCall.module.css";

interface ServerToolCallProps {
  id?: string;
  content: ContentToolUse;
  className?: string | string[];
}

/**
 * Renders the ToolOutput component.
 */
export const ServerToolCall: FC<ServerToolCallProps> = ({
  id,
  content,
  className,
}) => {
  return <McpToolUse id={id} content={content} className={className} />;
};

const McpToolUse: FC<ServerToolCallProps> = ({ id, content, className }) => {
  // Resolve the arguments from the content
  const args = resolveArgs(content);

  const titleStr = content.context
    ? `${content.context} — ${content.name}()`
    : `${content.name}()`;

  const listToolsResult = maybeListTools(content);
  const webSearchResult = maybeWebSearchResult(content);

  return (
    <div id={id} className={clsx(styles.mcpToolUse, className)}>
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
        {Object.keys(args).map((key, index) => {
          const value = args[key];

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

        {webSearchResult ? (
          <>
            <LabelDiv label={"results"} />
            <ValueDiv>
              {webSearchResult.result.map((result, index) => (
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

        {listToolsResult
          ? (listToolsResult.result as ToolInfo[]).map((tool, index) => (
              <>
                <ExpandablePanel
                  id={`${id}-output`}
                  collapse={true}
                  className={clsx(styles.toolPanel)}
                >
                  <LabelDiv label={tool.name} />
                  <ValueDiv>
                    <div>{tool.description}</div>
                    <RecordTree
                      id={`${id}-tool-${index}`}
                      record={{ schema: tool.input_schema }}
                      defaultExpandLevel={0}
                    />
                  </ValueDiv>
                </ExpandablePanel>
              </>
            ))
          : undefined}
      </div>

      {content.error ? (
        <div className={styles.error}>
          <span>Error: {content.error}</span>
        </div>
      ) : !listToolsResult && !webSearchResult ? (
        <div className={clsx("text-size-small")}>
          <ExpandablePanel id={`${id}-output`} collapse={true}>
            <RenderedContent
              id={`${id}-output`}
              entry={{ name: "Output", value: content.result }}
              renderOptions={{ renderString: "markdown" }}
            />
          </ExpandablePanel>
        </div>
      ) : undefined}
    </div>
  );
};

const resolveArgs = (content: ContentToolUse): Record<string, unknown> => {
  if (typeof content.arguments === "string") {
    // See if this looks like a JSON object
    if (isJson(content.arguments)) {
      try {
        return JSON.parse(content.arguments);
      } catch (e) {
        console.warn("Failed to parse arguments as JSON", e);
      }
    }
    if (content.arguments) {
      return { arguments: content.arguments };
    }
    return {};
  } else if (typeof content.arguments === "object") {
    return content.arguments as Record<string, unknown>;
  } else if (content.arguments) {
    return { arguments: content.arguments };
  } else {
    return {};
  }
};

const maybeWebSearchResult = (
  content: ContentToolUse,
): { result: WebResult[] } | undefined => {
  if (content.name !== "web_search") {
    return undefined;
  }
  const objArray = asJsonObjArray(content.result);
  if (objArray !== undefined) {
    return { result: objArray as WebResult[] };
  }
};

const maybeListTools = (
  content: ContentToolUse,
): { result: ToolInfo[] } | undefined => {
  if (content.name !== "mcp_list_tools") {
    return undefined;
  }
  const objArray = asJsonObjArray(content.result);
  if (objArray !== undefined) {
    return { result: objArray as ToolInfo[] };
  }
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

interface ToolInfo {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}
