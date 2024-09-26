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

/**
 * Renders the ToolEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ToolEvent} props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @param { number } props.depth - The depth of this event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const ToolEventView = ({ id, event, style, depth }) => {
  // Extract tool input
  const { input, functionCall, inputType } = resolveToolInput(
    event.function,
    event.arguments,
  );
  const title = `Tool: ${event.function}`;
  const output = event.result || event.error?.message;
  return html`
  <${EventPanel} id=${id} title="${title}" icon=${ApplicationIcons.solvers.use_tools} style=${style}>
    <div name="Summary" style=${{ width: "100%", margin: "0.5em 0" }}>
        ${
          !output
            ? "(No output)"
            : html`
          <${ExpandablePanel} collapse=${true} border=${true} lines=10>
            <${ToolOutput}
              output=${output}
            />
          </${ExpandablePanel}>`
        }
    </div>
    
  
  <div name="Transcript" style=${{ margin: "0.5em 0" }}>
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
                depth=${depth + 1}
              />`
            : ""
        }

  </div>
  </${EventPanel}>`;
};
