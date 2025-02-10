import { useMemo } from "react";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { ContentTool } from "../../../types";
import {
  ContentAudio,
  ContentImage,
  ContentText,
  ContentVideo,
  ToolCallContent,
} from "../../../types/log";
import { MessageContent } from "../MessageContent";
import { ToolInput } from "./ToolInput";
import { ToolTitle } from "./ToolTitle";

interface ToolCallViewProps {
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
    | (
        | ContentText
        | ContentAudio
        | ContentImage
        | ContentVideo
        | ContentTool
      )[];
  mode?: "compact";
}

/**
 * Renders the ToolCallView component.
 */
export const ToolCallView: React.FC<ToolCallViewProps> = ({
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
      | ContentTool,
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

  return (
    <div>
      {mode !== "compact" && (!view || view.title) ? (
        <ToolTitle title={view?.title || functionCall} />
      ) : (
        ""
      )}
      <div>
        <div>
          <ToolInput
            highlightLanguage={highlightLanguage}
            contents={input}
            toolCallView={view}
          />
          <ExpandablePanel collapse={collapse} border={true} lines={15}>
            <MessageContent contents={normalizedContent} />
          </ExpandablePanel>
        </div>
      </div>
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
    | (
        | ContentText
        | ContentImage
        | ContentAudio
        | ContentVideo
        | ContentTool
      )[],
): (
  | ContentText
  | ContentImage
  | ContentAudio
  | ContentVideo
  | ContentTool
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
          },
        ],
      },
    ];
  }
};
