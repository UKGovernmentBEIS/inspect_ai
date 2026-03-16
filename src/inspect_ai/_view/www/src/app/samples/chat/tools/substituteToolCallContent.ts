import { ToolCallContent } from "../../../../@types/log";

/**
 * Substitute `{{param_name}}` placeholders in a ToolCallContent from arguments.
 * Unmatched placeholders are left as-is.
 */
export const substituteToolCallContent = (
  content: ToolCallContent,
  args: Record<string, unknown>,
): ToolCallContent => {
  const replace = (text: string): string =>
    text.replace(/\{\{(\w+)\}\}/g, (match, key: string) =>
      Object.hasOwn(args, key) ? String(args[key]) : match,
    );

  return {
    ...content,
    title: content.title ? replace(content.title) : content.title,
    content: replace(content.content),
  };
};
