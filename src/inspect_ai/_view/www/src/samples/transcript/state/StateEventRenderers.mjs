// @ts-check
import { html } from "htm/preact";
import { ChatView } from "../../../components/ChatView.mjs";
import { FontSize, TextStyle } from "../../../appearance/Fonts.mjs";

/**
 * @typedef {Object} Signature
 * @property {string[]} remove - Array of paths to be removed.
 * @property {string[]} replace - Array of paths to be replaced.
 * @property {string[]} add - Array of paths to be added.
 */

/**
 * @typedef {Object} ChangeType
 * @property {string} type - Type of the system message.
 * @property {Signature} signature - Signature of the system message.
 * @property {function(import("../../../types/log").JsonChange[], Object): import("preact").JSX.Element} render - Function to render the resolved state.
 */

/** @type {ChangeType} */
const system_msg_added_sig = {
  type: "system_message",
  signature: {
    remove: ["/messages/0/source"],
    replace: ["/messages/0/role", "/messages/0/content"],
    add: ["/messages/1"],
  },
  render: (_changes, resolvedState) => {
    const message = resolvedState["messages"][0];
    return html`<${ChatView}
      id="system_msg_event_preview"
      messages=${[message]}
    />`;
  },
};

const kToolPattern = "/tools/(\\d+)";

/** @type {ChangeType} */
const use_tools = {
  type: "use_tools",
  signature: {
    add: ["/tools/0"],
    replace: ["/tool_choice"],
    remove: [],
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  },
};

/** @type {ChangeType} */
const add_tools = {
  type: "add_tools",
  signature: {
    add: [kToolPattern],
    replace: [],
    remove: [],
  },
  render: (changes, resolvedState) => {
    return renderTools(changes, resolvedState);
  },
};

const renderTools = (changes, resolvedState) => {
  // Find which tools were added in this change
  const toolIndexes = [];
  for (const change of changes) {
    const match = change.path.match(kToolPattern);
    if (match) {
      toolIndexes.push(match[1]);
    }
  }

  const toolName = (toolChoice) => {
    if (typeof toolChoice === "object" && toolChoice) {
      return toolChoice["name"];
    } else {
      return toolChoice;
    }
  };

  const toolsInfo = {};

  // Show tool choice if it was changed
  const hasToolChoice = changes.find((change) => {
    return change.path.startsWith("/tool_choice");
  });
  if (resolvedState.tool_choice && hasToolChoice) {
    toolsInfo["Tool Choice"] = toolName(resolvedState.tool_choice);
  }

  // Show either all tools or just the specific tools
  if (resolvedState.tools.length > 0) {
    if (toolIndexes.length === 0) {
      toolsInfo["Tools"] = html`<${Tools}
        toolDefinitions=${resolvedState.tools}
      />`;
    } else {
      const filtered = resolvedState.tools.filter((_, index) => {
        return toolIndexes.includes(index.toString());
      });
      toolsInfo["Tools"] = html`<${Tools} toolDefinitions=${filtered} />`;
    }
  }

  return html`
    <div
      style=${{
        display: "grid",
        gridTemplateColumns: "max-content max-content",
        columnGap: "1rem",
        margin: "0",
      }}
    >
      ${Object.keys(toolsInfo).map((key) => {
        return html` <div
            style=${{
              fontSize: FontSize.smaller,
              ...TextStyle.label,
              ...TextStyle.secondary,
            }}
          >
            ${key}
          </div>
          <div style=${{ fontSize: FontSize.base }}>${toolsInfo[key]}</div>`;
      })}
    </div>
  `;
};

/** @type {ChangeType[]} */
export const RenderableChangeTypes = [
  system_msg_added_sig,
  use_tools,
  add_tools,
];

/**
 * @typedef {Object} ToolParameters
 * @property {string} type - The type of the parameters object, typically "object".
 * @property {Object} properties - An object describing the properties of the parameters.
 * @property {ToolProperty} properties.code - The code property, which is a string.
 * @property {string[]} required - An array of required property names.
 */

/**
 * @typedef {Object} ToolProperty
 * @property {string} type - The data type of the property (e.g., "string").
 * @property {string} description - A description of the property.
 */

/**
 * @typedef {Object} ToolDefinition
 * @property {string} name - The name of the tool (e.g., "python").
 * @property {string} description - A brief description of what the tool does.
 * @property {ToolParameters} parameters - An object describing the parameters that the tool accepts.
 */

/**
 * Renders a list of tool components based on the provided tool definitions.
 *
 * @param {Object} props - The component props.
 * @param {ToolDefinition[]} props.toolDefinitions - An array of tool definition objects, each containing the function name and arguments.
 *
 * @returns {import("preact").JSX.Element[]} An array of JSX elements representing the tools.
 */
export const Tools = ({ toolDefinitions }) => {
  return toolDefinitions.map((toolDefinition) => {
    const toolName = toolDefinition.name;
    const toolArgs = Object.keys(toolDefinition.parameters.properties);
    return html`<${Tool} toolName=${toolName} toolArgs=${toolArgs} />`;
  });
};

/**
 * Renders a single tool component.
 *
 * @param {Object} props - The component props.
 * @param {string} props.toolName - The name of the tool to be displayed.
 * @param {string[]} [props.toolArgs] - An optional array of arguments for the tool (not used in the current implementation).
 * @param {string} [props.toolDesc] - An optional description of the tool (not used in the current implementation).
 *
 * @returns {import("preact").JSX.Element} A JSX element representing the tool.
 */
export const Tool = ({ toolName, toolArgs }) => {
  const functionCall =
    toolArgs && toolArgs.length > 0
      ? `${toolName}(${toolArgs.join(", ")})`
      : toolName;
  return html`<div>
    <code style=${{ fontSize: FontSize.small, padding: "0" }}
      >${functionCall}</code
    >
  </div>`;
};
