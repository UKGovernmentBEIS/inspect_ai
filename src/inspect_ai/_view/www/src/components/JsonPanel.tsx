import clsx from "clsx";
import { highlightElement } from "prismjs";
import React, { useEffect, useMemo, useRef } from "react";
import "./JsonPanel.css";

const kPrismRenderMaxSize = 250000;

interface JSONPanelProps {
  id?: string;
  data?: unknown;
  json?: string;
  simple?: boolean;
  style?: React.CSSProperties;
  className?: string | string[];
}

export const JSONPanel: React.FC<JSONPanelProps> = ({
  id,
  json,
  data,
  simple = false,
  style,
  className,
}) => {
  const codeRef = useRef<HTMLElement>(null);
  const sourceCode = useMemo(() => {
    return json || JSON.stringify(resolveBase64(data), undefined, 2);
  }, [json, data]);

  useEffect(() => {
    if (sourceCode.length < kPrismRenderMaxSize && codeRef.current) {
      highlightElement(codeRef.current);
    }
  }, [sourceCode]);

  return (
    <pre
      className={clsx("json-panel", simple ? "simple" : "", className)}
      style={style}
    >
      <code
        id={id}
        ref={codeRef}
        className={clsx("source-code", "language-javascript")}
      >
        {sourceCode}
      </code>
    </pre>
  );
};

export default JSONPanel;

export const resolveBase64 = (value: any): any => {
  const prefix = "data:image";

  // Handle arrays recursively
  if (Array.isArray(value)) {
    return value.map((v) => resolveBase64(v));
  }

  // Handle objects recursively
  if (value && typeof value === "object") {
    const resolvedObject: Record<string, unknown> = {};
    for (const key of Object.keys(value)) {
      resolvedObject[key] = resolveBase64(value[key]);
    }
    return resolvedObject;
  }

  // Handle string values with protocol references
  if (typeof value === "string") {
    let resolvedValue = value;
    if (resolvedValue.startsWith(prefix)) {
      resolvedValue = "[base64 image]";
    }
    return resolvedValue;
  }

  // Return unchanged for other types
  return value;
};
