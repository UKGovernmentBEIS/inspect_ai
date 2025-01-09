// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { ANSIDisplay } from "../../components/AnsiDisplay.mjs";
import { formatDateTime } from "../../utils/Format.mjs";

/**
 * Renders the ErrorEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").ErrorEvent} props.event - The event object to display.
 * @param { Object } props.style - The style of this event.
 * @param {import("./Types.mjs").TranscriptEventState} props.eventState - The state for this event
 * @param {(state: import("./Types.mjs").TranscriptEventState) => void} props.setEventState - Update the state for this event
 * @returns {import("preact").JSX.Element} The component.
 */
export const ErrorEventView = ({
  id,
  event,
  style,
  eventState,
  setEventState,
}) => {
  return html`
  <${EventPanel} 
    id=${id} 
    title="Error" 
    subTitle=${formatDateTime(new Date(event.timestamp))} 
    icon=${ApplicationIcons.error} 
    style=${style}
    selectedNav=${eventState.selectedNav || ""}
    onSelectedNav=${(selectedNav) => {
      setEventState({ ...eventState, selectedNav });
    }}
    collapsed=${eventState.collapsed}
    onCollapsed=${(collapsed) => {
      setEventState({ ...eventState, collapsed });
    }}
  >
    <${ANSIDisplay} output=${event.error.traceback_ansi} style=${{ fontSize: "clamp(0.5rem, calc(0.25em + 1vw), 0.8rem)", margin: "0.5em 0" }}/>
  </${EventPanel}>`;
};
