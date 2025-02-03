import { ApplicationIcons } from "../../appearance/icons";
import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
  ContentAudio,
  ContentImage,
  ContentText,
  ContentVideo,
  Messages,
} from "../../types/log";

export interface ResolvedMessage {
  message: ChatMessageAssistant | ChatMessageSystem | ChatMessageUser;
  toolMessages: ChatMessageTool[];
}

export const resolveMessages = (messages: Messages) => {
  // Filter tool messages into a sidelist that the chat stream
  // can use to lookup the tool responses

  const resolvedMessages: ResolvedMessage[] = [];
  for (const message of messages) {
    if (message.role === "tool") {
      // Add this tool message onto the previous message
      if (resolvedMessages.length > 0) {
        const msg = resolvedMessages[resolvedMessages.length - 1];

        msg.toolMessages = msg.toolMessages || [];
        msg.toolMessages.push(message);
      }
    } else {
      resolvedMessages.push({ message, toolMessages: [] });
    }
  }

  // Capture system messages (there could be multiple)
  const systemMessages: ChatMessageSystem[] = [];
  const collapsedMessages = resolvedMessages
    .map((resolved) => {
      if (resolved.message.role === "system") {
        systemMessages.push(resolved.message);
      }
      return resolved;
    })
    .filter((resolved) => {
      return resolved.message.role !== "system";
    });

  // Collapse system messages
  const systemContent: (
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
  )[] = [];
  for (const systemMessage of systemMessages) {
    const contents = Array.isArray(systemMessage.content)
      ? systemMessage.content
      : [systemMessage.content];
    systemContent.push(...contents.map(normalizeContent));
  }

  const systemMessage: ChatMessageSystem = {
    role: "system",
    content: systemContent,
    source: "input",
  };

  // Converge them
  if (systemMessage && systemMessage.content.length > 0) {
    collapsedMessages.unshift({ message: systemMessage, toolMessages: [] });
  }
  return collapsedMessages;
};

export const iconForMsg = (
  msg:
    | ChatMessageAssistant
    | ChatMessageSystem
    | ChatMessageUser
    | ChatMessageTool,
) => {
  if (msg.role === "user") {
    return ApplicationIcons.role.user;
  } else if (msg.role === "system") {
    return ApplicationIcons.role.system;
  } else if (msg.role === "tool") {
    return ApplicationIcons.role.tool;
  } else if (msg.role === "assistant") {
    return ApplicationIcons.role.assistant;
  } else {
    return ApplicationIcons.role.unknown;
  }
};

/**
 * Normalize strings
 */
const normalizeContent = (
  content: ContentText | ContentImage | ContentAudio | ContentVideo | string,
): ContentText | ContentImage | ContentAudio | ContentVideo => {
  if (typeof content === "string") {
    return {
      type: "text",
      text: content,
    };
  } else {
    return content;
  }
};
