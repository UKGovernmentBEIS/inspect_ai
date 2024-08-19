// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { ExpandablePanel } from "../../components/ExpandablePanel.mjs";
import { resolveToolInput, ToolCallView } from "../../components/Tools.mjs";
import { TranscriptView } from "./TranscriptView.mjs";

/**
 * Renders the InfoEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { number } props.depth - The depth of this event.
 * @param {import("../../types/log").ToolEvent} props.event - The event object to display.
 * @param {import("./TranscriptState.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ToolEventView = ({ id, depth, stateManager, event }) => {
  // Extract tool input
  const { input, functionCall, inputType } = resolveToolInput(
    event.function,
    event.arguments,
  );
  const title = `Tool: ${event.function}`;

  return html`
  <${EventPanel} id=${id} depth=${depth} title="${title}" icon=${ApplicationIcons.solvers.use_tools}>
  <div name="Result">
    <${ExpandablePanel}>
    ${event.result}
    </${ExpandablePanel}>
  </div>
  <div name="Complete">
    <${ToolCallView}
      functionCall=${functionCall}
      input=${input}
      inputType=${inputType}
      output=${event.result}
      mode="compact"
      />
  </div>
  ${
    event.events.length > 0
      ? html`<${TranscriptView}
          id="${id}-subtask"
          name="Transcript"
          events=${event.events}
          stateManager=${stateManager}
        />`
      : ""
  }
  </${EventPanel}>`;
};
