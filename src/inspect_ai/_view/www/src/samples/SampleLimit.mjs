//

/**
 * Formats a limit message
 *
 * @param {import("../types/log").Type11} [type] - The limit type
 * @returns {string} The limit message
 */
export const sampleLimitMessage = (type) => {
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
    default:
      return undefined;
  }
};
