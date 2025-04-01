import clsx from "clsx";
import { CSSProperties, FC, useMemo } from "react";
import { usePrismHighlight } from "../state/hooks";
import "./JsonPanel.css";

interface JSONPanelProps {
  id?: string;
  data?: unknown;
  json?: string;
  simple?: boolean;
  style?: CSSProperties;
  className?: string | string[];
}

export const JSONPanel: FC<JSONPanelProps> = ({
  id,
  json,
  data,
  simple = false,
  style,
  className,
}) => {
  const sourceCode = useMemo(() => {
    return json || JSON.stringify(resolveBase64(data), undefined, 2);
  }, [json, data]);
  const prismParentRef = usePrismHighlight(sourceCode);

  return (
    <div ref={prismParentRef}>
      <pre
        className={clsx("json-panel", simple ? "simple" : "", className)}
        style={style}
      >
        <code id={id} className={clsx("source-code", "language-javascript")}>
          {sourceCode}
        </code>
      </pre>
    </div>
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
