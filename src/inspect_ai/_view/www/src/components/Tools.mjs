// @ts-check

/**
 * @typedef {Object} ToolCallResult
 * @property {string} functionCall - The formatted function call with arguments.
 * @property {string|undefined} input - The primary input for the tool, if available.
 * @property {string|undefined} inputType - The type of the input (e.g., "bash", "python", "text"), if applicable.
 */

/**
 * Resolves the input and metadata for a given tool call.
 *
 * @param {import("../types/log").ToolCall} tool_call - The tool call object containing the function name and arguments.
 *
 * @returns {ToolCallResult}  An object containing the following properties:
 */
export const resolveToolInput = (tool_call) => {
  const toolName = tool_call.function;

  const extractInputMetadata = () => {
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
  const [inputKey, inputType] = extractInputMetadata();

  const extractInput = (inputKey, tool_call) => {
    const formatArg = (key, value) => {
      const quotedValue = typeof value === "string" ? `"${value}"` : value;
      return `${key}: ${quotedValue}`;
    };

    if (tool_call.arguments) {
      if (Object.keys(tool_call.arguments).length === 1) {
        return {
          input: tool_call.arguments[Object.keys(tool_call.arguments)[0]],
          args: [],
        };
      } else if (tool_call.arguments[inputKey]) {
        const input = tool_call.arguments[inputKey];
        const args = Object.keys(tool_call.arguments)
          .filter((key) => {
            return key !== inputKey;
          })
          .map((key) => {
            return formatArg(key, tool_call.arguments[key]);
          });
        return {
          input,
          args,
        };
      } else {
        const args = Object.keys(tool_call.arguments).map((key) => {
          return formatArg(key, tool_call.arguments[key]);
        });

        return {
          input: undefined,
          args: args,
        };
      }
    }
    return {
      input: undefined,
      args: [],
    };
  };
  const { input, args } = extractInput(inputKey, tool_call);

  const functionCall =
    args.length > 0 ? `${toolName}(${args.join(",")})` : toolName;
  return {
    functionCall,
    input,
    inputType,
  };
};
