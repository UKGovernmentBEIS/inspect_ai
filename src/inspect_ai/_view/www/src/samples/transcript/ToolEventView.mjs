// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { ExpandablePanel } from "../../components/ExpandablePanel.mjs";
import {
  resolveToolInput,
  ToolCallView,
  ToolOutput,
} from "../../components/Tools.mjs";
import { TranscriptView } from "./TranscriptView.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";

/**
 * Renders the ToolEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ToolEvent} props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @param {import("./Types.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @param { number } props.depth - The depth of this event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ToolEventView = ({ id, event, style, stateManager, depth }) => {
  // Extract tool input
  const { input, functionCall, inputType } = resolveToolInput(
    event.function,
    event.arguments,
  );
  const title = `Tool: ${event.function}`;

  return html`
  <${EventPanel} id=${id} title="${title}" icon=${ApplicationIcons.solvers.use_tools} style=${style}>
  <div name="Summary">
    <${ExpandablePanel}>
      ${event.result ? html`<${ToolOutput} output=${event.result} style=${{ margin: "1em 0" }} />` : html`<div style=${{ margin: "1em 0", fontSize: FontSize.small }}>No output</div>`}
    </${ExpandablePanel}>
  </div>
  <div name="Transcript" style=${{ margin: "1em 0" }}>
    <${ToolCallView}
      functionCall=${functionCall}
      input=${input}
      inputType=${inputType}
      output=${event.result}
      mode="compact"
      />
        ${
          event.events.length > 0
            ? html`<${TranscriptView}
                id="${id}-subtask"
                name="Transcript"
                events=${event.events}
                stateManager=${stateManager}
                depth=${depth + 1}
              />`
            : ""
        }

  </div>
  </${EventPanel}>`;
};
