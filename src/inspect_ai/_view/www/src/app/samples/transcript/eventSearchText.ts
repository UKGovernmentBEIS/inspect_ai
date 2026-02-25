import {
  ApprovalEvent,
  CompactionEvent,
  Content,
  ContentReasoning,
  ContentText,
  ContentToolUse,
  ErrorEvent,
  InfoEvent,
  InputEvent,
  LoggerEvent,
  ModelEvent,
  SampleInitEvent,
  SampleLimitEvent,
  SandboxEvent,
  ScoreEditEvent,
  ScoreEvent,
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
      if (modelEvent.role) {
        texts.push(`Model Call (${modelEvent.role}): ${modelEvent.model}`);
      } else {
        texts.push(`Model Call: ${modelEvent.model}`);
      }
      if (modelEvent.output?.choices) {
        for (const choice of modelEvent.output.choices) {
          texts.push(...extractContentText(choice.message.content));
        }
      }
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
      texts.push(`Tool: ${toolEvent.view?.title || toolEvent.function}`);
      if (toolEvent.function) {
        texts.push(toolEvent.function);
      }
      if (toolEvent.arguments) {
        texts.push(JSON.stringify(toolEvent.arguments));
      }
      if (toolEvent.result) {
        if (typeof toolEvent.result === "string") {
          texts.push(toolEvent.result);
        } else {
          texts.push(JSON.stringify(toolEvent.result));
        }
      }
      if (toolEvent.error?.message) {
        texts.push(toolEvent.error.message);
      }
      break;
    }

    case "error": {
      const errorEvent = event as ErrorEvent;
      texts.push("Error");
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
      if (loggerEvent.message?.level) {
        texts.push(loggerEvent.message.level);
      }
      if (loggerEvent.message?.message) {
        texts.push(loggerEvent.message.message);
      }
      if (loggerEvent.message?.filename) {
        texts.push(loggerEvent.message.filename);
      }
      break;
    }

    case "info": {
      const infoEvent = event as InfoEvent;
      texts.push("Info");
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

    case "compaction": {
      const compactionEvent = event as CompactionEvent;
      texts.push("Compaction");
      if (compactionEvent.source) {
        texts.push(compactionEvent.source);
      }
      texts.push(JSON.stringify(compactionEvent));
      break;
    }

    case "step": {
      const stepEvent = event as StepEvent;
      texts.push(
        stepEvent.type
          ? `${stepEvent.type}: ${stepEvent.name}`
          : `Step: ${stepEvent.name}`,
      );
      break;
    }

    case "subtask": {
      const subtaskEvent = event as SubtaskEvent;
      texts.push(
        subtaskEvent.type === "fork"
          ? `Fork: ${subtaskEvent.name}`
          : `Subtask: ${subtaskEvent.name}`,
      );
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
      texts.push(
        spanEvent.type
          ? `${spanEvent.type}: ${spanEvent.name}`
          : `Step: ${spanEvent.name}`,
      );
      break;
    }

    case "score": {
      const scoreEvent = event as ScoreEvent;
      texts.push(
        (scoreEvent.intermediate ? "Intermediate " : "") + "Score",
      );
      if (scoreEvent.score.answer) {
        texts.push(scoreEvent.score.answer);
      }
      if (scoreEvent.score.explanation) {
        texts.push(scoreEvent.score.explanation);
      }
      if (scoreEvent.target) {
        const target = Array.isArray(scoreEvent.target)
          ? scoreEvent.target.join("\n")
          : scoreEvent.target;
        texts.push(target);
      }
      if (scoreEvent.score.value != null) {
        texts.push(
          typeof scoreEvent.score.value === "object"
            ? JSON.stringify(scoreEvent.score.value)
            : String(scoreEvent.score.value),
        );
      }
      break;
    }

    case "score_edit": {
      const scoreEditEvent = event as ScoreEditEvent;
      texts.push("Edit Score");
      if (scoreEditEvent.edit.answer) {
        texts.push(scoreEditEvent.edit.answer);
      }
      if (scoreEditEvent.edit.explanation) {
        texts.push(scoreEditEvent.edit.explanation);
      }
      if (scoreEditEvent.edit.provenance) {
        if (scoreEditEvent.edit.provenance.author) {
          texts.push(scoreEditEvent.edit.provenance.author);
        }
        if (scoreEditEvent.edit.provenance.reason) {
          texts.push(scoreEditEvent.edit.provenance.reason);
        }
      }
      break;
    }

    case "sample_init": {
      const sampleInitEvent = event as SampleInitEvent;
      texts.push("Sample");
      if (sampleInitEvent.sample.target) {
        const target = Array.isArray(sampleInitEvent.sample.target)
          ? sampleInitEvent.sample.target.join("\n")
          : sampleInitEvent.sample.target;
        texts.push(target);
      }
      break;
    }

    case "sample_limit": {
      const sampleLimitEvent = event as SampleLimitEvent;
      const limitTitles: Record<string, string> = {
        custom: "Custom Limit Exceeded",
        time: "Time Limit Exceeded",
        message: "Message Limit Exceeded",
        token: "Token Limit Exceeded",
        operator: "Operator Canceled",
        working: "Execution Time Limit Exceeded",
        cost: "Cost Limit Exceeded",
      };
      texts.push(
        limitTitles[sampleLimitEvent.type] ?? sampleLimitEvent.type,
      );
      if (sampleLimitEvent.message) {
        texts.push(sampleLimitEvent.message);
      }
      break;
    }

    case "input": {
      const inputEvent = event as InputEvent;
      texts.push("Input");
      if (inputEvent.input_ansi) {
        texts.push(inputEvent.input_ansi);
      }
      break;
    }

    case "approval": {
      const approvalEvent = event as ApprovalEvent;
      const decisionLabels: Record<string, string> = {
        approve: "Approved",
        reject: "Rejected",
        terminate: "Terminated",
        escalate: "Escalated",
        modify: "Modified",
      };
      texts.push(
        decisionLabels[approvalEvent.decision] ?? approvalEvent.decision,
      );
      if (approvalEvent.explanation) {
        texts.push(approvalEvent.explanation);
      }
      break;
    }

    case "sandbox": {
      const sandboxEvent = event as SandboxEvent;
      texts.push(`Sandbox: ${sandboxEvent.action}`);
      if (sandboxEvent.cmd) {
        texts.push(sandboxEvent.cmd);
      }
      if (sandboxEvent.file) {
        texts.push(sandboxEvent.file);
      }
      if (sandboxEvent.input) {
        texts.push(sandboxEvent.input);
      }
      if (sandboxEvent.output) {
        texts.push(sandboxEvent.output);
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
