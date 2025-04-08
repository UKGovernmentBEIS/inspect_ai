import clsx from "clsx";
import { diff } from "jsondiffpatch";
import { format } from "jsondiffpatch/formatters/html";
import { FC } from "react";

interface StateDiffViewProps {
  before: Object;
  after: Object;
  className?: string | string[];
}

/**
 * Renders a view displaying a list of state changes.
 */
export const StateDiffView: FC<StateDiffViewProps> = ({
  before,
  after,
  className,
}) => {
  // Diff the objects and render the diff
  const state_diff = diff(sanitizeKeys(before), sanitizeKeys(after));

  const html_result = format(state_diff) || "Unable to render differences";
  return (
    <div
      dangerouslySetInnerHTML={{ __html: unescapeNewlines(html_result) }}
      className={clsx(className)}
    ></div>
  );
};

function unescapeNewlines<T>(obj: T): T {
  if (typeof obj === "string") {
    return obj.replace(/\\n/g, "\n") as T;
  }

  if (obj === null || typeof obj !== "object") {
    return obj;
  }

  if (Array.isArray(obj)) {
    return obj.map((item) => unescapeNewlines(item)) as T;
  }

  return Object.fromEntries(
    Object.entries(obj as Record<string, unknown>).map(([key, value]) => [
      key,
      unescapeNewlines(value),
    ]),
  ) as T;
}

function sanitizeKeys<T>(obj: T): T {
  if (typeof obj !== "object" || obj === null) {
    return obj;
  }

  if (Array.isArray(obj)) {
    return obj.map((item) => sanitizeKeys(item)) as T;
  }

  return Object.fromEntries(
    Object.entries(obj as Record<string, unknown>).map(([key, value]) => [
      key.replace(/</g, "&lt;").replace(/>/g, "&gt;"),
      sanitizeKeys(value),
    ]),
  ) as T;
}
