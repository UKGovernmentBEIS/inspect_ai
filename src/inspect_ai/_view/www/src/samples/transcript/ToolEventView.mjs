// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { resolveToolInput, ToolCallView } from "../../components/Tools.mjs";
import { TranscriptView } from "./TranscriptView.mjs";
import { ApprovalEventView } from "./ApprovalEventView.mjs";
import { formatDateTime } from "../../utils/Format.mjs";

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

  // Find an approval if there is one
  const approvalEvent = event.events.find((e) => {
    return e.event === "approval";
  });

  const title = `Tool: ${event.view?.title || event.function}`;
  return html`
  <${EventPanel} id=${id} title="${title}" subTitle=${formatDateTime(new Date(event.timestamp))} icon=${ApplicationIcons.solvers.use_tools} style=${style}>  
  <div name="Summary" style=${{ margin: "0.5em 0", width: "100%" }}>
    <${ToolCallView}
      functionCall=${functionCall}
      input=${input}
      inputType=${inputType}
      output=${event.result}
      mode="compact"
      view=${event.view}
      />
      ${
        approvalEvent
          ? html`<${ApprovalEventView}
              id="${id}-approval"
              event=${approvalEvent}
              style=${{ border: "none", padding: 0, marginBottom: 0 }}
            />`
          : ""
      }
  </div>
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
  </${EventPanel}>`;
};
