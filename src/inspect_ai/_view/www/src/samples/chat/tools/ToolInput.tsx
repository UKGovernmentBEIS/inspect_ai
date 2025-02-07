import clsx from "clsx";
import murmurhash from "murmurhash";
import { highlightElement, languages } from "prismjs";
import { useEffect, useRef } from "react";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { ToolCallContent } from "../../../types/log";
import styles from "./ToolInput.module.css";

interface ToolInputProps {
  type?: string;
  contents?: string;
  view?: ToolCallContent;
}

/**
 * Renders the ToolInput component.
 */
export const ToolInput: React.FC<ToolInputProps> = ({
  type,
  contents,
  view,
}) => {
  if (!contents && !view?.content) {
    return null;
  }

  if (view) {
    const toolViewRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
      // Sniff around for code in the view that could be text highlighted
      if (toolViewRef.current) {
        for (const child of toolViewRef.current.children) {
          if (child.tagName === "PRE") {
            const childChild = child.firstElementChild;
            if (childChild && childChild.tagName === "CODE") {
              const hasLanguageClass = Array.from(childChild.classList).some(
                (className) => className.startsWith("language-"),
              );
              if (hasLanguageClass) {
                child.classList.add("tool-output");
                highlightElement(childChild as HTMLElement);
              }
            }
          }
        }
      }
    }, [contents, view]);
    return (
      <MarkdownDiv
        markdown={view.content}
        ref={toolViewRef}
        className={clsx(styles.bottomMargin)}
      />
    );
  } else {
    const toolInputRef = useRef(null);
    useEffect(() => {
      if (type) {
        const tokens = languages[type];
        if (toolInputRef.current && tokens) {
          highlightElement(toolInputRef.current);
        }
      }
    }, [contents, type, view]);

    contents =
      typeof contents === "object" || Array.isArray(contents)
        ? JSON.stringify(contents)
        : contents;
    const key = murmurhash.v3(contents || "");

    return (
      <pre
        className={clsx("tool-output", styles.outputPre, styles.bottomMargin)}
      >
        <code
          ref={toolInputRef}
          key={key}
          className={clsx("source-code", `language-${type}`, styles.outputCode)}
        >
          {contents}
        </code>
      </pre>
    );
  }
};
