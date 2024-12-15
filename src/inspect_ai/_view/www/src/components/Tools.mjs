// @ts-check
/// <reference path="../types/prism.d.ts" />
import Prism from "prismjs";
import murmurhash from "murmurhash";

import "prismjs/components/prism-python";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-json";

import { useRef, useEffect } from "preact/hooks";
import { html } from "htm/preact";

import { MessageContent } from "./MessageContent.mjs";
import { ExpandablePanel } from "./ExpandablePanel.mjs";
import { FontSize } from "../appearance/Fonts.mjs";
import { MarkdownDiv } from "./MarkdownDiv.mjs";

/**
 * @typedef {Object} ToolCallResult
 * @property {string} functionCall - The formatted function call with arguments.
 * @property {string|undefined} input - The primary input for the tool, if available.
 * @property {string|undefined} inputType - The type of the input (e.g., "bash", "python", "text"), if applicable.
 */

/**
 * Resolves the input and metadata for a given tool call.
 * @param { string } fn - The tool call function name
 * @param { import("../types/log").Arguments } toolArgs - The tool call arguments
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
 * @param {Object} props - The parameters for the component.
 * @param {string} props.functionCall - The function call
 * @param {string | undefined } props.input - The main input for this call
 * @param {string | undefined } props.inputType - The input type for this call
 * @param {import("../types/log").ToolCallContent} props.view - The tool call view
 * @param {string | number | boolean | (import("../types/log").ContentText | import("../types/log").ContentImage)[]} props.output - The tool output
 * @param { "compact" | undefined } props.mode - The display mode for this call
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const ToolCallView = ({
  functionCall,
  input,
  inputType,
  view,
  output,
  mode,
}) => {
  return html`<div>
    ${mode !== "compact" && (!view || view.title)
      ? html`<${ToolTitle} title=${view?.title || functionCall} />`
      : ""}
    <div>
      <div>
        <${ToolInput}
          type=${inputType}
          contents=${input}
          view=${view}
          style=${{ marginBottom: "1em" }}
        />
        ${output
          ? html`
              <${ExpandablePanel} collapse=${true} border=${true} lines=${15}>
              <${MessageContent} contents=${normalizeContent(output)} />
              </${ExpandablePanel}>`
          : ""}
      </div>
    </div>
  </div>`;
};

/**
 * Renders the ToolCallView component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.title - The title for the tool call
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
const ToolTitle = ({ title }) => {
  return html` <i
      class="bi bi-tools"
      style=${{
        marginRight: "0.2rem",
        opacity: "0.4",
      }}
    ></i>
    <code style=${{ fontSize: FontSize.small }}>${title}</code>`;
};

/**
 * Renders the ToolCallView component.
 *
 * @param {string | number | boolean | (import("../types/log").ContentText | import("../types/log").ContentImage)[]} output - The tool output
 * @returns {(import("../Types.mjs").ContentTool | import("../types/log").ContentText | import("../types/log").ContentImage)[]} The SampleTranscript component.
 */
const normalizeContent = (output) => {
  if (Array.isArray(output)) {
    return output;
  } else {
    return [
      {
        type: "tool",
        content: [
          {
            type: "text",
            text: String(output),
          },
        ],
      },
    ];
  }
};

/**
 * Renders the ToolInput component.
 *
 * @param {Object} props - The parameters for the component.
 * @param {string} props.type - The function call
 * @param {string | undefined } props.contents - The main input for this call
 * @param {Record<string, string>} [props.style] - The style
 * @param {import("../types/log").ToolCallContent} [props.view] - The tool call view
 * @returns {import("preact").JSX.Element | string} The SampleTranscript component.
 */
export const ToolInput = ({ type, contents, view, style }) => {
  if (!contents && !view?.content) {
    return "";
  }

  if (view) {
    const toolInputRef = useRef(/** @type {HTMLElement|null} */ (null));
    useEffect(() => {
      // Sniff around for code in the view that could be text highlighted
      if (toolInputRef.current) {
        for (const child of toolInputRef.current.base.children) {
          if (child.tagName === "PRE") {
            const childChild = child.firstElementChild;
            if (childChild && childChild.tagName === "CODE") {
              const hasLanguageClass = Array.from(childChild.classList).some(
                (className) => className.startsWith("language-"),
              );
              if (hasLanguageClass) {
                child.classList.add("tool-output");
                Prism.highlightElement(childChild);
              }
            }
          }
        }
      }
    }, [contents, view, style]);
    return html`<${MarkdownDiv}
      markdown=${view.content}
      ref=${toolInputRef}
      style=${style}
    />`;
  } else {
    const toolInputRef = useRef(/** @type {HTMLElement|null} */ (null));
    useEffect(() => {
      const tokens = Prism.languages[type];
      if (toolInputRef.current && tokens) {
        Prism.highlightElement(toolInputRef.current);
      }
    }, [contents, type, view]);

    contents =
      typeof contents === "object" || Array.isArray(contents)
        ? JSON.stringify(contents)
        : contents;
    const key = murmurhash.v3(contents);

    return html`<pre
      class="tool-output"
      style=${{
        padding: "0.5em",
        marginTop: "0.25em",
        marginBottom: "1rem",
        ...style,
      }}
    >
        <code ref=${toolInputRef} 
          key=${key}
          class="sourceCode${type ? ` language-${type}` : ""}" style=${{
      overflowWrap: "anywhere",
      whiteSpace: "pre-wrap",
    }}>
          ${contents}
          </code>
      </pre>`;
  }
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
 * @returns {{ input: string | undefined, args: string[] }}
 */
const extractInput = (inputKey, args) => {
  const formatArg = (key, value) => {
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
