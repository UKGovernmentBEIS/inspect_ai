import clsx from "clsx";
import { FC, Ref, useRef } from "react";

import { usePrismHighlight } from "../../../../state/hooks";
import { RenderedText } from "../../../content/RenderedText";
import styles from "./ToolInput.module.css";
import { kToolTodoContentType } from "./tool";
import { TodoWriteInput } from "./tool-input/TodoWriteInput";

interface ToolInputProps {
  contentType?: string;
  contents?: unknown | object;
  toolCallView?: { content: string };
  className?: string | string[];
}
export const ToolInput: FC<ToolInputProps> = (props) => {
  const { contentType, contents, toolCallView, className } = props;

  const sourceCodeRef = useRef<HTMLDivElement | null>(null);

  const sourceCodeLength = toolCallView
    ? toolCallView.content.length
    : contents
      ? typeof contents === "string"
        ? contents.length
        : JSON.stringify(contents).length
      : 0;
  usePrismHighlight(sourceCodeRef, sourceCodeLength);

  if (!contents && !toolCallView?.content) return null;

  if (toolCallView) {
    return (
      <RenderedText
        markdown={toolCallView.content}
        ref={sourceCodeRef}
        className={clsx("tool-output", styles.toolView, className)}
      />
    );
  } else {
    return (
      <RenderTool
        contents={contents!}
        contentType={contentType || ""}
        parentRef={sourceCodeRef}
        className={className}
      />
    );
  }
};

interface RenderToolProps {
  contents: string | object;
  contentType: string;
  parentRef: Ref<HTMLDivElement>;
  className?: string | string[];
}

const RenderTool: FC<RenderToolProps> = ({
  contents,
  contentType,
  parentRef,
  className,
}) => {
  if (contentType === kToolTodoContentType) {
    return <TodoWriteInput contents={contents} parentRef={parentRef} />;
  }

  const formattedContent =
    typeof contents === "object" ? JSON.stringify(contents) : contents;

  return (
    <div ref={parentRef}>
      <pre
        className={clsx(
          "tool-output",
          styles.outputPre,
          styles.bottomMargin,
          className,
        )}
      >
        <code
          className={clsx(
            "source-code",
            "sourceCode",
            contentType ? `language-${contentType}` : undefined,
            styles.outputCode,
          )}
        >
          {formattedContent}
        </code>
      </pre>
    </div>
  );
};
