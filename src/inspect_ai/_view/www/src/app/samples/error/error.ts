/**
 * Extracts the error type from a given message.
 * If the message contains parentheses, it returns the substring before the first parenthesis.
 * Otherwise, it returns "Error".
 */
export const errorType = (message?: string): string => {
  if (!message) {
    return "Error";
  }

  if (message.includes("(")) {
    return message.split("(")[0];
  }
  return "Error";
};
