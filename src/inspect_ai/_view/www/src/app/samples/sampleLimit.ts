import { Type21 } from "../../@types/log";

/**
 * Formats a limit message
 */
export const sampleLimitMessage = (type: Type21): string => {
  switch (type) {
    case "operator":
      return "Sample terminated due to operator limit.";
    case "message":
      return "Sample terminated due to message limit.";
    case "time":
      return "Sample terminated due to time limit.";
    case "token":
      return "Sample terminated due to token limit.";
    case "context":
      return "Sample terminated due to context limit.";
    case "cost":
      return "Sample terminated due to cost limit.";
    default:
      return "An unknown limit terminated this sample.";
  }
};
