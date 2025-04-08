import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";

import { Arguments } from "../../../../@types/log";

export interface ToolCallResult {
  functionCall: string;
  input?: string;
  highlightLanguage?: string;
}

/**
 * Resolves the input and metadata for a given tool call.
 */
export const resolveToolInput = (
  fn: string,
  toolArgs: Arguments,
): ToolCallResult => {
  const toolName = fn;

  const [inputKey, highlightLanguage] = extractInputMetadata(toolName);
  const { input, args } = extractInput(
    toolArgs as Record<string, unknown>,
    inputKey,
  );
  const functionCall =
    args.length > 0 ? `${toolName}(${args.join(", ")})` : toolName;
  return {
    functionCall,
    input,
    highlightLanguage,
  };
};

const extractInputMetadata = (
  toolName: string,
): [string | undefined, string | undefined] => {
  if (toolName === "bash") {
    return ["cmd", "bash"];
  } else if (toolName === "python") {
    return ["code", "python"];
  } else if (toolName === "web_search") {
    return ["query", "text"];
  } else {
    return [undefined, undefined];
  }
};

const extractInput = (
  args: Record<string, unknown>,
  inputKey?: string,
): { input?: string; args: string[] } => {
  const formatArg = (key: string, value: unknown) => {
    const quotedValue =
      value === null
        ? "None"
        : typeof value === "string"
          ? `"${value}"`
          : typeof value === "object" || Array.isArray(value)
            ? JSON.stringify(value, undefined, 2)
            : String(value);
    return `${key}: ${quotedValue}`;
  };
  if (args) {
    if (inputKey && args[inputKey]) {
      const input = args[inputKey];
      const filteredArgs = Object.keys(args)
        .filter((key) => {
          return key !== inputKey;
        })
        .map((key) => {
          return formatArg(key, args[key]);
        });
      return {
        input: String(input),
        args: filteredArgs,
      };
    } else {
      const formattedArgs = Object.keys(args).map((key) => {
        return formatArg(key, args[key]);
      });

      return {
        input: undefined,
        args: formattedArgs,
      };
    }
  }
  return {
    input: undefined,
    args: [],
  };
};
