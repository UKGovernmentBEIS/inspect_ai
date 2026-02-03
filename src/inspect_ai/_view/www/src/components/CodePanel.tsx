import { FC, useRef } from "react";

import clsx from "clsx";

import styles from "./CodePanel.module.css";
import { usePrismHighlight } from "./prism";

interface CodePanelProps {
  code: string;
  language?: string;
}

export const CodePanel: FC<CodePanelProps> = ({ code, language = "json" }) => {
  // Syntax highlighting
  const codeContainerRef = useRef<HTMLDivElement>(null);
  usePrismHighlight(codeContainerRef, code.length);
  return (
    <div ref={codeContainerRef} className={clsx(styles.panel)}>
      <pre className={clsx(styles.code)}>
        <code className={clsx(`language-${language}`)}>{code}</code>
      </pre>
    </div>
  );
};
