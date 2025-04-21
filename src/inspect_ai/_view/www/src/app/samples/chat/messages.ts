import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
  ContentAudio,
  ContentImage,
  ContentReasoning,
  ContentText,
  ContentVideo,
  Events,
  Messages,
} from "../../../@types/log";
import { ApplicationIcons } from "../../appearance/icons";

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
    | ContentReasoning
  )[] = [];
  for (const systemMessage of systemMessages) {
    const contents = Array.isArray(systemMessage.content)
      ? systemMessage.content
      : [systemMessage.content];
    systemContent.push(...contents.map(normalizeContent));
  }

  const systemMessage: ChatMessageSystem = {
    id: "sys-message-6815A84B062A",
    role: "system",
    content: systemContent,
    source: "input",
    internal: null,
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
  content:
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
    | ContentReasoning
    | string,
):
  | ContentText
  | ContentImage
  | ContentAudio
  | ContentVideo
  | ContentReasoning => {
  if (typeof content === "string") {
    return {
      type: "text",
      text: content,
      refusal: null,
    };
  } else {
    return content;
  }
};

export const messagesFromEvents = (runningEvents: Events): Messages => {
  const messages: Map<
    string,
    ChatMessageSystem | ChatMessageUser | ChatMessageAssistant | ChatMessageTool
  > = new Map();

  runningEvents
    .filter((e) => e.event === "model")
    .forEach((e) => {
      for (const m of e.input) {
        const inputMessage = m as
          | ChatMessageSystem
          | ChatMessageUser
          | ChatMessageAssistant
          | ChatMessageTool;
        if (inputMessage.id && !messages.has(inputMessage.id)) {
          messages.set(inputMessage.id, inputMessage);
        }
      }
      const outputMessage = e.output.choices[0].message;
      if (outputMessage.id) {
        messages.set(outputMessage.id, outputMessage);
      }
    });

  if (messages.size > 0) {
    return messages.values().toArray();
  } else {
    return [];
  }
};
