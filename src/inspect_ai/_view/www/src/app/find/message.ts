import {
  ChatMessageAssistant,
  ChatMessageSystem,
  ChatMessageTool,
  ChatMessageUser,
  Messages,
} from "../../@types/log";

export const findMessageIndexes = (term: string, messages: Messages) => {
  const result: Record<number, number> = {};
  for (let i = 0; i < messages.length; i++) {
    const message = messages[i];
    const count = find(term, message);
    if (count > 0) {
      result[i] = count;
    }
  }
  console.log({ result });
  return result;
};

export const find = (
  term: string,
  message:
    | ChatMessageAssistant
    | ChatMessageSystem
    | ChatMessageUser
    | ChatMessageTool,
): number => {
  let matches = 0;
  if (typeof message.content === "string") {
    matches = countWord(message.content, term);
  } else {
    for (const content of message.content) {
      switch (content.type) {
        case "text":
          matches += countWord(content.text, term);
          break;
        case "reasoning":
          matches += countWord(content.reasoning, term);
          break;
        // TODO: tool calls input / output
      }
    }
  }
  return matches;
};

function countWord(text: string, word: string): number {
  return text.toLowerCase().split(word.toLowerCase()).length - 1;
}
