import { Content } from "../../../@types/log";
import { substituteToolCallContent } from "../chat/tools/substituteToolCallContent";
import { eventTitle } from "./event/utils";
import { EventNode } from "./types";

/**
 * Extracts searchable text from an EventNode for find-in-page functionality.
 */
export const eventSearchText = (node: EventNode): string[] => {
  const texts: string[] = [];
  const event = node.event;

  const title = eventTitle(event);
  if (title) {
    texts.push(title);
  }

  switch (event.event) {
    case "model": {
      if (event.output?.choices) {
        for (const choice of event.output.choices) {
          texts.push(...extractContentText(choice.message.content));
        }
      }
      // Model event error details (API errors, tracebacks)
      if (event.error) {
        if (typeof event.error === "string") {
          texts.push(event.error);
        }
      }
      break;
    }

    case "tool": {
      if (event.function) {
        texts.push(event.function);
      }
      if (event.arguments && typeof event.arguments === "string") {
        texts.push(event.arguments);
      } else if (event.arguments && typeof event.arguments === "object") {
        texts.push(JSON.stringify(event.arguments));
      }
      if (event.result && typeof event.result === "string") {
        texts.push(event.result);
      } else if (event.result != null) {
        texts.push(...extractToolResultText(event.result));
      }
      if (event.error?.message) {
        texts.push(event.error.message);
      }
      if (event.view?.content) {
        const substituted = substituteToolCallContent(
          event.view,
          event.arguments as Record<string, unknown>,
        );
        texts.push(substituted.content);
      }
      break;
    }

    case "error": {
      if (event.error?.message) {
        texts.push(event.error.message);
      }
      break;
    }

    case "logger": {
      if (event.message?.message) {
        texts.push(event.message.message);
      }
      if (event.message?.filename) {
        texts.push(event.message.filename);
      }
      break;
    }

    case "info": {
      if (event.data && typeof event.data === "string") {
        texts.push(event.data);
      }
      break;
    }

    case "compaction": {
      if (event.source) {
        texts.push(event.source);
      }
      break;
    }

    case "subtask": {
      if (event.input && typeof event.input === "string") {
        texts.push(event.input);
      }
      if (event.result && typeof event.result === "string") {
        texts.push(event.result);
      }
      break;
    }

    case "score": {
      if (event.score.answer) {
        texts.push(event.score.answer);
      }
      if (event.score.explanation) {
        texts.push(event.score.explanation);
      }
      if (event.target) {
        const target = Array.isArray(event.target)
          ? event.target.join("\n")
          : event.target;
        texts.push(target);
      }
      if (event.score.value != null) {
        texts.push(
          typeof event.score.value === "object"
            ? JSON.stringify(event.score.value)
            : String(event.score.value),
        );
      }
      break;
    }

    case "score_edit": {
      if (event.edit.answer) {
        texts.push(event.edit.answer);
      }
      if (event.edit.explanation) {
        texts.push(event.edit.explanation);
      }
      if (event.edit.provenance) {
        if (event.edit.provenance.author) {
          texts.push(event.edit.provenance.author);
        }
        if (event.edit.provenance.reason) {
          texts.push(event.edit.provenance.reason);
        }
      }
      break;
    }

    case "sample_init": {
      if (event.sample.target) {
        const target = Array.isArray(event.sample.target)
          ? event.sample.target.join("\n")
          : event.sample.target;
        texts.push(target);
      }
      break;
    }

    case "sample_limit": {
      if (event.message) {
        texts.push(event.message);
      }
      break;
    }

    case "input": {
      if (event.input_ansi) {
        texts.push(event.input_ansi);
      }
      break;
    }

    case "approval": {
      if (event.explanation) {
        texts.push(event.explanation);
      }
      break;
    }

    case "sandbox": {
      if (event.cmd) {
        texts.push(event.cmd);
      }
      if (event.file) {
        texts.push(event.file);
      }
      if (event.input) {
        texts.push(event.input);
      }
      if (event.output) {
        texts.push(event.output);
      }
      break;
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
        texts.push(item.text);
        break;
      case "reasoning": {
        if (item.reasoning) {
          texts.push(item.reasoning);
        } else if (item.summary) {
          texts.push(item.summary);
        }
        break;
      }
      case "tool_use": {
        if (item.name) {
          texts.push(item.name);
        }
        if (item.arguments && typeof item.arguments === "string") {
          texts.push(item.arguments);
        }
        break;
      }
    }
  }
  return texts;
};

const extractToolResultText = (value: unknown): string[] => {
  if (value == null) {
    return [];
  }

  if (
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return [String(value)];
  }

  if (Array.isArray(value)) {
    return value.flatMap((item) => extractToolResultText(item));
  }

  if (typeof value !== "object") {
    return [];
  }

  const item = value as Record<string, unknown>;
  const type = item.type;

  if (type === "text" && typeof item.text === "string") {
    return [item.text];
  }

  if (type === "reasoning") {
    const out: string[] = [];
    if (typeof item.reasoning === "string") {
      out.push(item.reasoning);
    }
    if (typeof item.summary === "string") {
      out.push(item.summary);
    }
    return out;
  }

  if (type === "tool" && Array.isArray(item.content)) {
    return item.content.flatMap((c) => extractToolResultText(c));
  }

  if (type === "image" && typeof item.image === "string") {
    return item.image.startsWith("data:") ? [] : [item.image];
  }

  return [JSON.stringify(value)];
};
