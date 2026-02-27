import { Content } from "../../../@types/log";
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
      if (event.input) {
        for (const msg of event.input) {
          if (msg.role === "user" || msg.role === "system") {
            texts.push(...extractContentText(msg.content));
          }
        }
      }
      break;
    }

    case "tool": {
      if (event.function) {
        texts.push(event.function);
      }
      if (event.arguments) {
        texts.push(JSON.stringify(event.arguments));
      }
      if (event.result) {
        if (typeof event.result === "string") {
          texts.push(event.result);
        } else {
          texts.push(JSON.stringify(event.result));
        }
      }
      if (event.error?.message) {
        texts.push(event.error.message);
      }
      break;
    }

    case "error": {
      if (event.error?.message) {
        texts.push(event.error.message);
      }
      if (event.error?.traceback) {
        texts.push(event.error.traceback);
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
      if (event.data) {
        if (typeof event.data === "string") {
          texts.push(event.data);
        } else {
          texts.push(JSON.stringify(event.data));
        }
      }
      break;
    }

    case "compaction": {
      if (event.source) {
        texts.push(event.source);
      }
      texts.push(JSON.stringify(event));
      break;
    }

    case "subtask": {
      if (event.input) {
        texts.push(JSON.stringify(event.input));
      }
      if (event.result) {
        texts.push(JSON.stringify(event.result));
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
        if (item.arguments) {
          texts.push(JSON.stringify(item.arguments));
        }
        break;
      }
    }
  }
  return texts;
};
