import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
  Content,
  ContentAudio,
  ContentData,
  ContentDocument,
  ContentImage,
  ContentReasoning,
  ContentText,
  ContentToolUse,
  ContentVideo,
  Messages,
} from "../../@types/log";

export interface MessagesToStrOptions {
  excludeSystem?: boolean;
  excludeToolUsage?: boolean;
  excludeReasoning?: boolean;
}

export const messagesToStr = (
  messages: Messages,
  options?: MessagesToStrOptions,
): string => {
  const opts = options || {};
  return messages
    .map((msg) => messageToStr(msg, opts))
    .filter((str): str is string => str !== null)
    .join("\n");
};

const messageToStr = (
  message:
    | ChatMessageSystem
    | ChatMessageUser
    | ChatMessageAssistant
    | ChatMessageTool,
  options: MessagesToStrOptions,
): string | null => {
  // Exclude system messages if requested
  if (options.excludeSystem && message.role === "system") {
    return null;
  }

  const content = betterContentText(
    message.content,
    options.excludeToolUsage || false,
    options.excludeReasoning || false,
  );

  // Handle assistant messages with tool calls
  if (
    !options.excludeToolUsage &&
    message.role === "assistant" &&
    (message as ChatMessageAssistant).tool_calls
  ) {
    const assistantMsg = message as ChatMessageAssistant;
    let entry = `${message.role.toUpperCase()}:\n${content}\n`;

    if (assistantMsg.tool_calls) {
      for (const tool of assistantMsg.tool_calls) {
        const funcName = tool.function;
        const args = tool.arguments;

        if (typeof args === "object" && args !== null) {
          const argsText = Object.entries(args)
            .map(([k, v]) => `${k}: ${v}`)
            .join("\n");
          entry += `\nTool Call: ${funcName}\nArguments:\n${argsText}\n`;
        } else {
          entry += `\nTool Call: ${funcName}\nArguments: ${args}\n`;
        }
      }
    }

    return entry;
  }

  // Handle tool messages
  if (message.role === "tool") {
    if (options.excludeToolUsage) {
      return null;
    }
    const toolMsg = message as ChatMessageTool;
    const funcName = toolMsg.function || "unknown";
    const errorPart = toolMsg.error
      ? `\n\nError in tool call '${funcName}':\n${toolMsg.error.message}\n`
      : "";
    return `${message.role.toUpperCase()}:\n${content}${errorPart}\n`;
  }

  // Default formatting for system, user, and assistant messages without tool calls
  return `${message.role.toUpperCase()}:\n${content}\n`;
};

const textFromContent = (
  content:
    | ContentText
    | ContentReasoning
    | ContentImage
    | ContentAudio
    | ContentVideo
    | ContentData
    | ContentToolUse
    | ContentDocument,
  excludeToolUsage: boolean,
  excludeReasoning: boolean,
): string | null => {
  switch (content.type) {
    case "text":
      return (content as ContentText).text;

    case "reasoning": {
      const reasoningContent = content as ContentReasoning;
      if (excludeReasoning) {
        return null;
      }
      const reasoning = reasoningContent.redacted
        ? reasoningContent.summary
        : reasoningContent.reasoning;
      if (!reasoning) {
        return null;
      }
      // Bracket it with start/finish since it could be multiple lines long
      return `\n<think>${reasoning}</think>`;
    }

    case "tool_use": {
      if (excludeToolUsage) {
        return null;
      }
      const toolUse = content as ContentToolUse;
      const errorStr = toolUse.error ? ` ${toolUse.error}` : "";
      return `\nTool Use: ${toolUse.name}(${toolUse.arguments}) -> ${toolUse.result}${errorStr}`;
    }

    case "image":
    case "audio":
    case "video":
    case "data":
    case "document":
      return `<${content.type} />`;

    default:
      return null;
  }
};

const betterContentText = (
  content: Content,
  excludeToolUsage: boolean,
  excludeReasoning: boolean,
): string => {
  if (typeof content === "string") {
    return content;
  }

  const allText = content
    .map((c) => textFromContent(c, excludeToolUsage, excludeReasoning))
    .filter((text): text is string => text !== null);

  return allText.join("\n");
};
