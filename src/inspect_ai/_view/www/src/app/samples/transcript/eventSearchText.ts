import {
  Content,
  ContentReasoning,
  ContentText,
  ContentToolUse,
  ErrorEvent,
  InfoEvent,
  LoggerEvent,
  ModelEvent,
  SpanBeginEvent,
  StepEvent,
  SubtaskEvent,
  ToolEvent,
} from "../../../@types/log";
import { EventNode } from "./types";

/**
 * Extracts searchable text from an EventNode for find-in-page functionality.
 */
export const eventSearchText = (node: EventNode): string[] => {
  const texts: string[] = [];
  const event = node.event;

  switch (event.event) {
    case "model": {
      const modelEvent = event as ModelEvent;
      // Model name (displayed in title)
      if (modelEvent.model) {
        texts.push(modelEvent.model);
      }
      // Extract text from model output
      if (modelEvent.output?.choices) {
        for (const choice of modelEvent.output.choices) {
          texts.push(...extractContentText(choice.message.content));
        }
      }
      // Extract text from user/system input messages shown in the view
      if (modelEvent.input) {
        for (const msg of modelEvent.input) {
          if (msg.role === "user" || msg.role === "system") {
            texts.push(...extractContentText(msg.content));
          }
        }
      }
      break;
    }

    case "tool": {
      const toolEvent = event as ToolEvent;
      // Custom tool title (displayed instead of function name)
      if (toolEvent.view?.title) {
        texts.push(toolEvent.view.title);
      }
      // Tool function name
      if (toolEvent.function) {
        texts.push(toolEvent.function);
      }
      // Tool arguments
      if (toolEvent.arguments) {
        texts.push(JSON.stringify(toolEvent.arguments));
      }
      // Tool result
      if (toolEvent.result) {
        if (typeof toolEvent.result === "string") {
          texts.push(toolEvent.result);
        } else {
          texts.push(JSON.stringify(toolEvent.result));
        }
      }
      // Tool error
      if (toolEvent.error?.message) {
        texts.push(toolEvent.error.message);
      }
      break;
    }

    case "error": {
      const errorEvent = event as ErrorEvent;
      if (errorEvent.error?.message) {
        texts.push(errorEvent.error.message);
      }
      if (errorEvent.error?.traceback) {
        texts.push(errorEvent.error.traceback);
      }
      break;
    }

    case "logger": {
      const loggerEvent = event as LoggerEvent;
      if (loggerEvent.message?.message) {
        texts.push(loggerEvent.message.message);
      }
      // Filename shown in the view
      if (loggerEvent.message?.filename) {
        texts.push(loggerEvent.message.filename);
      }
      break;
    }

    case "info": {
      const infoEvent = event as InfoEvent;
      // Source shown in title
      if (infoEvent.source) {
        texts.push(infoEvent.source);
      }
      if (infoEvent.data) {
        if (typeof infoEvent.data === "string") {
          texts.push(infoEvent.data);
        } else {
          texts.push(JSON.stringify(infoEvent.data));
        }
      }
      break;
    }

    case "step": {
      const stepEvent = event as StepEvent;
      if (stepEvent.name) {
        texts.push(stepEvent.name);
      }
      // Type shown in title (e.g., "solver: name")
      if (stepEvent.type) {
        texts.push(stepEvent.type);
      }
      break;
    }

    case "subtask": {
      const subtaskEvent = event as SubtaskEvent;
      if (subtaskEvent.name) {
        texts.push(subtaskEvent.name);
      }
      // Type shown in title
      if (subtaskEvent.type) {
        texts.push(subtaskEvent.type);
      }
      // Input/result shown in summary
      if (subtaskEvent.input) {
        texts.push(JSON.stringify(subtaskEvent.input));
      }
      if (subtaskEvent.result) {
        texts.push(JSON.stringify(subtaskEvent.result));
      }
      break;
    }

    case "span_begin": {
      const spanEvent = event as SpanBeginEvent;
      if (spanEvent.name) {
        texts.push(spanEvent.name);
      }
      // Type shown in title
      if (spanEvent.type) {
        texts.push(spanEvent.type);
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
