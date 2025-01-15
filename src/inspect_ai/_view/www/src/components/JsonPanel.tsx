import Prism from "prismjs";
import "prismjs/components/prism-json";
import React, { useEffect, useMemo, useRef } from "react";
import "./JSONPanel.css";

const kPrismRenderMaxSize = 250000;

interface JSONPanelProps {
  id?: string;
  data?: unknown;
  json?: string;
  simple?: boolean;
  style?: React.CSSProperties;
}

export const JSONPanel: React.FC<JSONPanelProps> = ({
  id,
  json,
  data,
  simple = false,
  style,
}) => {
  const codeRef = useRef<HTMLElement>(null);

  const sourceCode = useMemo(() => {
    return json || JSON.stringify(data, undefined, 2);
  }, [json, data]);

  useEffect(() => {
    if (sourceCode.length < kPrismRenderMaxSize && codeRef.current) {
      Prism.highlightElement(codeRef.current);
    }
  }, [sourceCode]);

  return (
    <div>
      <pre className={`json-panel ${simple ? "simple" : ""}`} style={style}>
        <code id={id} ref={codeRef} className="source-code language-javascript">
          {sourceCode}
        </code>
      </pre>
    </div>
  );
};

export default JSONPanel;
