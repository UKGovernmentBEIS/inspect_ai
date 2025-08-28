import clsx from "clsx";
import { FC } from "react";

import { usePrismHighlight } from "../../../../state/hooks";
import { RenderedText } from "../../../content/RenderedText";
import styles from "./ToolInput.module.css";

interface ToolInputProps {
  highlightLanguage?: string;
  contents?: string | object;
  toolCallView?: { content: string };
  className?: string | string[];
}
export const ToolInput: FC<ToolInputProps> = (props) => {
  const { highlightLanguage, contents, toolCallView, className } = props;

  const prismParentRef = usePrismHighlight(toolCallView?.content);

  if (!contents && !toolCallView?.content) return null;

  if (toolCallView) {
    return (
      <RenderedText
        markdown={toolCallView.content}
        ref={prismParentRef}
        className={clsx("tool-output", styles.toolView, className)}
      />
    );
  }

  const formattedContent =
    typeof contents === "object" ? JSON.stringify(contents) : contents;

  return (
    <div ref={prismParentRef}>
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
            highlightLanguage ? `language-${highlightLanguage}` : undefined,
            styles.outputCode,
          )}
        >
          {formattedContent}
        </code>
      </pre>
    </div>
  );
};
