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
import { NavPills } from "../../../../components/NavPills";
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
  /** Annotation derived from this visual action's own arguments. */
  selfAnnotation?: ToolAnnotation;
  /** Normalized content from the preceding screenshot (for the Input tab). */
  inputScreenshot?: (
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
    | ContentTool
  )[];
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
  selfAnnotation,
  inputScreenshot,
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

  // Build the output rendering (Result tab or standalone)
  const outputElement =
    hasContent && collapsible ? (
      <ExpandablePanel
        id={`${id}-tool-input`}
        collapse={collapse}
        border={true}
        lines={15}
        className={clsx("text-size-small")}
      >
        <MessageContent contents={normalizedContent} context={context} />
      </ExpandablePanel>
    ) : (
      <MessageContent contents={normalizedContent} context={context} />
    );

  // Build the input screenshot rendering (Input tab)
  const inputElement =
    selfAnnotation && inputScreenshot ? (
      <AnnotatedToolOutput annotation={selfAnnotation}>
        <MessageContent contents={inputScreenshot} context={context} />
      </AnnotatedToolOutput>
    ) : null;

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
      {inputElement ? (
        <NavPills id={`${id}-browser-action`}>
          <div title="Input">{inputElement}</div>
          <div title="Result">{outputElement}</div>
        </NavPills>
      ) : (
        outputElement
      )}
    </div>
  );
};

/**
 * Normalize tool output into a flat content array for MessageContent.
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
