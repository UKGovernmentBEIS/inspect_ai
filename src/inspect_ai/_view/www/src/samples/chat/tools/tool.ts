import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";

import { Arguments } from "../../../types/log";

export interface ToolCallResult {
  functionCall: string;
  input?: string;
  inputType?: string;
}

/**
 * Resolves the input and metadata for a given tool call.
 */
export const resolveToolInput = (
  fn: string,
  toolArgs: Arguments,
): ToolCallResult => {
  const toolName = fn;

  const [inputKey, inputType] = extractInputMetadata(toolName);
  if (inputKey) {
    const { input, args } = extractInput(
      inputKey,
      toolArgs as Record<string, unknown>,
    );
    const functionCall =
      args.length > 0 ? `${toolName}(${args.join(",")})` : toolName;
    return {
      functionCall,
      input,
      inputType,
    };
  } else {
    return {
      functionCall: toolName,
    };
  }
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
  inputKey: string,
  args: Record<string, unknown>,
): { input?: string; args: string[] } => {
  const formatArg = (key: string, value: unknown) => {
    const quotedValue = typeof value === "string" ? `"${value}"` : value;
    return `${key}: ${quotedValue}`;
  };
  if (args) {
    if (Object.keys(args).length === 1) {
      const inputRaw = args[Object.keys(args)[0]];

      let input;
      if (Array.isArray(inputRaw) || typeof inputRaw === "object") {
        input = JSON.stringify(inputRaw, undefined, 2);
      } else {
        input = String(inputRaw);
      }

      return {
        input: input,
        args: [],
      };
    } else if (args[inputKey]) {
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
