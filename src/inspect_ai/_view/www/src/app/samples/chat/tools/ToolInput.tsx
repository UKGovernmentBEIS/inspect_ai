import clsx from "clsx";
import { FC } from "react";
import { MarkdownDiv } from "../../../../components/MarkdownDiv";

import { usePrismHighlight } from "../../../../state/hooks";
import styles from "./ToolInput.module.css";

interface ToolInputProps {
  highlightLanguage?: string;
  contents?: string | object;
  toolCallView?: { content: string };
}
export const ToolInput: FC<ToolInputProps> = (props) => {
  const { highlightLanguage, contents, toolCallView } = props;

  const prismParentRef = usePrismHighlight(toolCallView?.content);

  if (!contents && !toolCallView?.content) return null;

  if (toolCallView) {
    return (
      <MarkdownDiv
        markdown={toolCallView.content}
        ref={prismParentRef}
        className={clsx("tool-output", styles.toolView)}
      />
    );
  }

  const formattedContent =
    typeof contents === "object" ? JSON.stringify(contents) : contents;

  return (
    <div ref={prismParentRef}>
      <pre
        className={clsx("tool-output", styles.outputPre, styles.bottomMargin)}
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
