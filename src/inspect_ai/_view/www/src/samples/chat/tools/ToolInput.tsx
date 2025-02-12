import clsx from "clsx";
import { highlightElement } from "prismjs";
import { memo, useEffect, useRef } from "react";
import { MarkdownDiv } from "../../../components/MarkdownDiv";

import styles from "./ToolInput.module.css";

export const useCodeHighlight = (language?: string) => {
  const codeRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (codeRef.current && language) {
      highlightElement(codeRef.current);
    }
  }, [language]);

  return codeRef;
};

interface ToolInputProps {
  highlightLanguage?: string;
  contents?: string | object;
  toolCallView?: { content: string };
}
export const ToolInput: React.FC<ToolInputProps> = memo((props) => {
  const { highlightLanguage, contents, toolCallView } = props;

  const codeRef = useCodeHighlight(highlightLanguage);

  if (!contents && !toolCallView?.content) return null;

  if (toolCallView) {
    const toolViewRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
      if (toolCallView?.content && toolViewRef.current) {
        requestAnimationFrame(() => {
          const codeBlocks = toolViewRef.current!.querySelectorAll("pre code");
          codeBlocks.forEach((block) => {
            if (block.className.includes("language-")) {
              block.classList.add("sourceCode");
              highlightElement(block as HTMLElement);
            }
          });
        });
      }
    }, [toolCallView?.content]);

    return (
      <MarkdownDiv
        markdown={toolCallView.content}
        ref={toolViewRef}
        className={clsx(styles.bottomMargin, "text-size-small")}
      />
    );
  }

  const formattedContent =
    typeof contents === "object" ? JSON.stringify(contents) : contents;

  return (
    <pre className={clsx("tool-output", styles.outputPre, styles.bottomMargin)}>
      <code
        ref={codeRef}
        className={clsx(
          "source-code",
          "sourceCode",
          `language-${highlightLanguage}`,
          styles.outputCode,
        )}
      >
        {formattedContent}
      </code>
    </pre>
  );
});
