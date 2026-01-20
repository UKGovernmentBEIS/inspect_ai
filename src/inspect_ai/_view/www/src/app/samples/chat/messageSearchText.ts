import {
  Content,
  ContentReasoning,
  ContentText,
  ContentToolUse,
} from "../../../@types/log";
import { ResolvedMessage } from "./messages";

/**
 * Extracts searchable text from a ResolvedMessage for find-in-page functionality.
 */
export const messageSearchText = (resolved: ResolvedMessage): string[] => {
  const texts: string[] = [];

  // Extract text from main message content
  texts.push(...extractContentText(resolved.message.content));

  // Extract tool call info from assistant messages
  if (
    resolved.message.role === "assistant" &&
    "tool_calls" in resolved.message &&
    resolved.message.tool_calls
  ) {
    for (const toolCall of resolved.message.tool_calls) {
      if (toolCall.function) {
        texts.push(toolCall.function);
      }
      if (toolCall.arguments) {
        texts.push(JSON.stringify(toolCall.arguments));
      }
    }
  }

  // Extract text from tool response messages
  for (const toolMsg of resolved.toolMessages) {
    // Tool function name (displayed as "tool: function_name")
    if (toolMsg.function) {
      texts.push(toolMsg.function);
    }
    texts.push(...extractContentText(toolMsg.content));
    if (toolMsg.error?.message) {
      texts.push(toolMsg.error.message);
    }
  }

  return texts;
};

/**
 * Extracts text strings from message content.
 */
const extractContentText = (content: Content): string[] => {
  if (typeof content === "string") {
    return [content];
  }

  const texts: string[] = [];
  for (const item of content) {
    switch (item.type) {
      case "text":
        texts.push((item as ContentText).text);
        break;
      case "reasoning": {
        const reasoning = item as ContentReasoning;
        if (reasoning.reasoning) {
          texts.push(reasoning.reasoning);
        } else if (reasoning.summary) {
          texts.push(reasoning.summary);
        }
        break;
      }
      case "tool_use": {
        const toolUse = item as ContentToolUse;
        if (toolUse.name) {
          texts.push(toolUse.name);
        }
        if (toolUse.arguments) {
          texts.push(JSON.stringify(toolUse.arguments));
        }
        break;
      }
    }
  }
  return texts;
};
