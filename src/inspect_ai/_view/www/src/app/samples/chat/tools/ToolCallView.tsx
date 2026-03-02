import clsx from "clsx";
import { FC, useMemo } from "react";
import {
  ContentAudio,
  ContentData,
  ContentImage,
  ContentReasoning,
  ContentText,
  ContentVideo,
  ToolCallContent,
} from "../../../../@types/log";
import { ContentTool } from "../../../../app/types";
import ExpandablePanel from "../../../../components/ExpandablePanel";
import { MessageContent } from "../MessageContent";
import { defaultContext } from "../MessageContents";
import styles from "./ToolCallView.module.css";
import { AnnotatedToolOutput, ToolAnnotation } from "./AnnotatedToolOutput";
import { ToolInput } from "./ToolInput";
import { ToolTitle } from "./ToolTitle";

interface ToolCallViewProps {
  id: string;
  functionCall: string;
  input?: unknown;
  precedingBrowserAction?: Record<string, unknown>;
  description?: string;
  contentType?: string;
  view?: ToolCallContent;
  output:
    | string
    | number
    | boolean
    | ContentText
    | ContentAudio
    | ContentImage
    | ContentVideo
    | ContentTool
    | ContentReasoning
    | ContentData
    | (
        | ContentText
        | ContentAudio
        | ContentImage
        | ContentVideo
        | ContentTool
        | ContentReasoning
        | ContentData
      )[];
  mode?: "compact";
  collapsible?: boolean;
}

/**
 * Renders the ToolCallView component.
 */
export const ToolCallView: FC<ToolCallViewProps> = ({
  id,
  functionCall,
  input,
  precedingBrowserAction,
  description,
  contentType,
  view,
  output,
  mode,
  collapsible = true,
}) => {
  // don't collapse if output includes an image
  function isContentImage(
    value:
      | string
      | number
      | boolean
      | ContentText
      | ContentAudio
      | ContentImage
      | ContentVideo
      | ContentTool
      | ContentReasoning
      | ContentData,
  ) {
    if (value && typeof value === "object") {
      if (value.type === "image") {
        return true;
      } else if (value.type === "tool") {
        if (
          Array.isArray(value.content) &&
          value.content.some(isContentImage)
        ) {
          return true;
        }
      }
    }
    return false;
  }

  const collapse = Array.isArray(output)
    ? output.every((item) => !isContentImage(item))
    : !isContentImage(output);
  const normalizedContent = useMemo(() => normalizeContent(output), [output]);

  const hasContent = normalizedContent.find((c) => {
    if (c.type === "tool") {
      for (const t of c.content) {
        if (t.type === "text") {
          if (t.text) {
            return true;
          }
        } else {
          return true;
        }
      }
      return false;
    } else {
      return true;
    }
  });

  const contents = mode !== "compact" ? input : input || functionCall;
  const context = defaultContext("tool");

  const annotation = useMemo<ToolAnnotation | undefined>(() => {
    // For screenshot tool calls, use the preceding browser action's arguments
    // to determine what annotation to show. The pattern is:
    //   browser(left_click, coord=[x,y]) → text response
    //   browser(screenshot) → image response ← annotate THIS with click info
    if (precedingBrowserAction) {
      const action = precedingBrowserAction.action as string | undefined;
      if (action) {
        return {
          action,
          coordinate: precedingBrowserAction.coordinate as
            | [number, number]
            | undefined,
          text: precedingBrowserAction.text as string | undefined,
          scrollDirection: precedingBrowserAction.scroll_direction as
            | string
            | undefined,
        };
      }
    }
    return undefined;
  }, [precedingBrowserAction]);

  return (
    <div className={clsx(styles.toolCallView)}>
      <div>
        {mode !== "compact" && (!view || view.title) ? (
          <ToolTitle
            title={view?.title || functionCall}
            description={description}
          />
        ) : (
          ""
        )}
        <ToolInput
          contentType={contentType}
          contents={contents}
          toolCallView={view}
        />
      </div>
      {hasContent && collapsible ? (
        <ExpandablePanel
          id={`${id}-tool-input`}
          collapse={collapse}
          border={true}
          lines={15}
          className={clsx("text-size-small")}
        >
          <AnnotatedToolOutput annotation={annotation}>
            <MessageContent contents={normalizedContent} context={context} />
          </AnnotatedToolOutput>
        </ExpandablePanel>
      ) : (
        <AnnotatedToolOutput annotation={annotation}>
          <MessageContent contents={normalizedContent} context={context} />
        </AnnotatedToolOutput>
      )}
    </div>
  );
};

/**
 * Renders the ToolCallView component.
 */
const normalizeContent = (
  output:
    | string
    | number
    | boolean
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
    | ContentTool
    | ContentReasoning
    | ContentData
    | (
        | ContentText
        | ContentImage
        | ContentAudio
        | ContentVideo
        | ContentTool
        | ContentReasoning
        | ContentData
      )[],
): (
  | ContentText
  | ContentImage
  | ContentAudio
  | ContentVideo
  | ContentTool
  | ContentReasoning
  | ContentData
)[] => {
  if (Array.isArray(output)) {
    return output;
  } else {
    return [
      {
        type: "tool",
        content: [
          {
            type: "text",
            text: String(output),
            refusal: null,
            internal: null,
            citations: null,
          },
        ],
      },
    ];
  }
};
