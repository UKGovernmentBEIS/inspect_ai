import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";
import "prismjs/components/prism-python";

import { Arguments1 } from "../../../../@types/log";

export const kToolTodoContentType = "agent/todo-list";
export interface ToolCallResult {
  functionCall: string;
  input?: unknown;
  description?: string;
  contentType?: string;
}

/**
 * Resolves the input and metadata for a given tool call.
 */
export const resolveToolInput = (
  fn: string,
  toolArgs: Arguments1,
): ToolCallResult => {
  const toolName = fn;

  const inputDescriptor = extractInputMetadata(toolName);
  const { input, description, args } = extractInput(
    toolArgs as Record<string, unknown>,
    inputDescriptor,
  );
  const functionCall =
    args.length > 0 ? `${toolName}(${args.join(", ")})` : toolName;
  return {
    functionCall,
    input,
    description,
    contentType: inputDescriptor?.contentType,
  };
};

interface ToolInputDescriptor {
  inputArg?: string;
  descriptionArg?: string;
  contentType?: string;
}

const extractInputMetadata = (
  toolName: string,
): ToolInputDescriptor | undefined => {
  if (toolName === "bash") {
    return {
      inputArg: "cmd",
      contentType: "bash",
    };
  } else if (toolName === "python") {
    return {
      inputArg: "code",
      contentType: "python",
    };
  } else if (toolName === "web_search") {
    return {
      inputArg: "query",
      contentType: "json",
    };
  } else if (toolName === "Bash") {
    return {
      inputArg: "command",
      descriptionArg: "description",
      contentType: "bash",
    };
  } else if (toolName == "TodoWrite") {
    return {
      inputArg: "todos",
      contentType: kToolTodoContentType,
    };
  } else {
    return undefined;
  }
};

const extractInput = (
  args: Record<string, unknown>,
  inputDescriptor?: ToolInputDescriptor,
): { input?: unknown; description?: string; args: string[] } => {
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

  // No args
  if (!args) {
    return {
      args: [],
    };
  }

  // Use the input descriptor to snip apart args
  if (inputDescriptor) {
    const filterKeys = new Set<string>();
    const base: { input?: unknown; description?: string } = {};

    if (inputDescriptor.inputArg && args[inputDescriptor.inputArg]) {
      filterKeys.add(inputDescriptor.inputArg);
      base.input = args[inputDescriptor.inputArg];
    }

    if (
      inputDescriptor.descriptionArg &&
      args[inputDescriptor.descriptionArg]
    ) {
      filterKeys.add(inputDescriptor.descriptionArg);
      base.description = String(args[inputDescriptor.descriptionArg]);
    }

    const filteredArgs = Object.keys(args)
      .filter((key) => {
        return !filterKeys.has(key);
      })
      .map((key) => {
        return formatArg(key, args[key]);
      });

    return {
      ...base,
      args: filteredArgs,
    };
  } else {
    const formattedArgs = Object.keys(args).map((key) => {
      return formatArg(key, args[key]);
    });

    return {
      args: formattedArgs,
    };
  }
};
