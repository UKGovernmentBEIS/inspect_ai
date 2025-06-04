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
import { ToolInput } from "./ToolInput";
import { ToolTitle } from "./ToolTitle";

interface ToolCallViewProps {
  id: string;
  functionCall: string;
  input?: string;
  highlightLanguage?: string;
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
}

/**
 * Renders the ToolCallView component.
 */
export const ToolCallView: FC<ToolCallViewProps> = ({
  id,
  functionCall,
  input,
  highlightLanguage,
  view,
  output,
  mode,
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
  const context = defaultContext();
  return (
    <div className={clsx(styles.toolCallView)}>
      <div>
        {mode !== "compact" && (!view || view.title) ? (
          <ToolTitle title={view?.title || functionCall} />
        ) : (
          ""
        )}
        <ToolInput
          highlightLanguage={highlightLanguage}
          contents={contents}
          toolCallView={view}
        />
      </div>
      {hasContent ? (
        <ExpandablePanel
          id={`${id}-tool-input`}
          collapse={collapse}
          border={true}
          lines={15}
          className={clsx("text-size-small")}
        >
          <MessageContent contents={normalizedContent} context={context} />
        </ExpandablePanel>
      ) : undefined}
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
