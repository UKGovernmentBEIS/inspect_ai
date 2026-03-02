import { ToolAnnotation } from "./AnnotatedToolOutput";

/**
 * Tool function names that produce browser/computer actions with annotations.
 * Inspect's built-in `computer` tool (used by osworld, etc.) and custom
 * `browser` tools both use the same action/coordinate argument shape.
 */
export const BROWSER_TOOL_FUNCTIONS = new Set(["browser", "computer"]);

/**
 * Set of browser actions that produce visual annotations
 * (click cursors, scroll arrows, typed text badges).
 */
export const VISUAL_BROWSER_ACTIONS = new Set([
  "left_click",
  "right_click",
  "middle_click",
  "double_click",
  "triple_click",
  "scroll",
  "type",
  "key",
]);

/**
 * Check whether a tool call is a visual browser action.
 */
export function isVisualBrowserAction(
  functionName: string,
  args: Record<string, unknown>,
): boolean {
  if (!BROWSER_TOOL_FUNCTIONS.has(functionName)) return false;
  const action = args?.action as string | undefined;
  return !!action && VISUAL_BROWSER_ACTIONS.has(action);
}

/**
 * Check whether a tool call is a browser screenshot.
 */
export function isBrowserScreenshot(
  functionName: string,
  args: Record<string, unknown>,
): boolean {
  return (
    BROWSER_TOOL_FUNCTIONS.has(functionName) && args?.action === "screenshot"
  );
}

/**
 * Build a ToolAnnotation from a visual browser action's own arguments.
 * Returns undefined if the action is not a visual browser action.
 */
export function buildSelfAnnotation(
  functionName: string,
  args: Record<string, unknown>,
): ToolAnnotation | undefined {
  if (!isVisualBrowserAction(functionName, args)) return undefined;
  const action = args.action as string;
  return {
    action,
    coordinate: args.coordinate as [number, number] | undefined,
    text: args.text as string | undefined,
    scrollDirection: args.scroll_direction as string | undefined,
  };
}
