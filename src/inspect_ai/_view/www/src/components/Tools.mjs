// @ts-check
/// <reference path="../types/prism.d.ts" />
import Prism from "prismjs";
import "prismjs/components/prism-python";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";

import { useRef, useEffect } from "preact/hooks";
import { html } from "htm/preact";

import { MessageContent } from "./MessageContent.mjs";
import { ExpandablePanel } from "./ExpandablePanel.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

/**
 * @typedef {Object} ToolCallResult
 * @property {string} functionCall - The formatted function call with arguments.
 * @property {string|undefined} input - The primary input for the tool, if available.
 * @property {string|undefined} inputType - The type of the input (e.g., "bash", "python", "text"), if applicable.
 */

/**
 * Resolves the input and metadata for a given tool call.
 * @param { string } fn - The tool call function name
 * @param { Record<string, unknown> } toolArgs - The tool call arguments
 *
 * @returns {ToolCallResult}  An object containing the following properties:
 */
export const resolveToolInput = (fn, toolArgs) => {
  const toolName = fn;

  const [inputKey, inputType] = extractInputMetadata(toolName);
  const { input, args } = extractInput(inputKey, toolArgs);
  const functionCall =
    args.length > 0 ? `${toolName}(${args.join(",")})` : toolName;
  return {
    functionCall,
    input,
    inputType,
  };
};

/**
 * Renders the ToolCallView component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.functionCall - The function call
 * @param {string | undefined } params.input - The main input for this call
 * @param {string | undefined } params.inputType - The input type for this call
 * @param {string | number | boolean | (import("../types/log").ContentText | import("../types/log").ContentImage)[]} params.output - The tool output
 * @param { "compact" | undefined } params.mode - The display mode for this call
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const ToolCallView = ({
  functionCall,
  input,
  inputType,
  output,
  mode,
}) => {
  const icon =
    mode === "compact"
      ? ""
      : html`<i
          class="bi bi-tools"
          style=${{
            marginRight: "0.2rem",
            opacity: "0.4",
          }}
        ></i>`;
  const codeIndent = mode === "compact" ? "" : "";
  return html`<div>
    ${icon}
    <code style=${{ fontSize: FontSize.small }}>${functionCall}</code>
    <div>
      <div style=${{ marginLeft: `${codeIndent}` }}>
        <${ToolInput} type=${inputType} contents=${input} />
        ${output
          ? html`
              <${ExpandablePanel} collapse=${true} border=${true} lines=${15}>
              <${MessageContent} contents=${output} />
              </${ExpandablePanel}>`
          : ""}
      </div>
    </div>
  </div>`;
};

/**
 * Renders the ToolInput component.
 *
 * @param {Object} params - The parameters for the component.
 * @param {string} params.type - The function call
 * @param {string | undefined } params.contents - The main input for this call
 * @returns {import("preact").JSX.Element | string} The SampleTranscript component.
 */
export const ToolInput = ({ type, contents }) => {
  if (!contents) {
    return "";
  }

  const toolInputRef = useRef(/** @type {HTMLElement|null} */ (null));

  if (typeof contents === "object" || Array.isArray(contents)) {
    contents = JSON.stringify(contents);
  }

  useEffect(() => {
    const tokens = Prism.languages[type];
    if (toolInputRef.current && tokens) {
      const html = Prism.highlight(contents, tokens, type);
      toolInputRef.current.innerHTML = html;
    }
  }, [toolInputRef.current, contents, type]);

  return html`<pre
    class="tool-output"
    style=${{
      padding: "0.5em",
      marginTop: "0.25em",
      marginBottom: "1rem",
    }}
  >
      <code ref=${toolInputRef} class="sourceCode${type
    ? ` language-${type}`
    : ""}" style=${{
    overflowWrap: "anywhere",
    whiteSpace: "pre-wrap",
  }}>
        ${contents}
        </code>
    </pre>`;
};

/**
 * Renders the ToolOutput component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string | number | boolean | (import("../types/log").ContentText | import("../types/log").ContentImage)[]} props.output - The tool output
 * @param {Object} props.style - The style for the element
 * @returns { import("preact").JSX.Element | import("preact").JSX.Element[] | string} The ToolOutput component.
 */
export const ToolOutput = ({ output, style }) => {
  // If there is no output, don't show the tool
  if (!output) {
    return "";
  }

  // First process an array or object into a string
  const outputs = [];
  if (Array.isArray(output)) {
    output.forEach((out) => {
      if (out.type === "text") {
        outputs.push(
          html`<${ToolTextOutput} text=${out.text} style=${style} />`,
        );
      } else {
        if (out.image.startsWith("data:")) {
          outputs.push(
            html`<img
              src="${out.image}"
              style=${{
                maxWidth: "100%",
                border: "solid var(--bs-border-color) 1px",
                ...style,
              }}
            />`,
          );
        } else {
          outputs.push(
            html`<${ToolTextOutput}
              text=${String(out.image)}
              style=${style}
            />`,
          );
        }
      }
    });
  } else {
    outputs.push(
      html`<${ToolTextOutput} text=${String(output)} style=${style} />`,
    );
  }
  return html`<div style=${{ display: "grid" }}>${outputs}</div>`;
};

/**
 * Renders the ToolTextOutput component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.text - The tool text
 * @param {Object} props.style - The style for the element
 * @returns {import("preact").JSX.Element} The ToolOutput component.
 */
const ToolTextOutput = ({ text, style }) => {
  return html`<pre
    style=${{
      marginLeft: "2px",
      padding: "0.5em 0.5em 0.5em 0.5em",
      whiteSpace: "pre-wrap",
      marginBottom: "0",
      ...style,
    }}
  >
    <code class="sourceCode" style=${{ wordWrap: "anywhere" }}>
      ${text.trim()}
      </code>
  </pre>`;
};

/**
 * @param {string} toolName
 * @returns {[string | undefined, string | undefined]}
 */
const extractInputMetadata = (toolName) => {
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

/**
 * @param {string} inputKey
 * @param {Object<string, any>} args
 * @returns {{ input: any, args: string[] }}
 */
const extractInput = (inputKey, args) => {
  const formatArg = (key, value) => {
    const quotedValue = typeof value === "string" ? `"${value}"` : value;
    return `${key}: ${quotedValue}`;
  };

  if (args) {
    if (Object.keys(args).length === 1) {
      return {
        input: args[Object.keys(args)[0]],
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
        input,
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
