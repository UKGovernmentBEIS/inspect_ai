import clsx from "clsx";
import { highlightElement } from "prismjs";
import { FC, memo, useEffect, useRef } from "react";
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
export const ToolInput: FC<ToolInputProps> = memo((props) => {
  const { highlightLanguage, contents, toolCallView } = props;

  const codeRef = useCodeHighlight(highlightLanguage);
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

  if (!contents && !toolCallView?.content) return null;

  if (toolCallView) {
    return (
      <MarkdownDiv
        markdown={toolCallView.content}
        ref={toolViewRef}
        className={clsx("text-size-small", "tool-output")}
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
          highlightLanguage ? `language-${highlightLanguage}` : undefined,
          styles.outputCode,
        )}
      >
        {formattedContent}
      </code>
    </pre>
  );
});
