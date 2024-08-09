// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./TranscriptView.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { MetaDataView } from "../../components/MetaDataView.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").SubtaskEvent} props.event - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SubtaskEventView = ({ id, event }) => {
  return html`
    <${EventPanel} id=${id} title="Subtask: ${event.name}">
      <${SubtaskSummary} name="Summary" input=${event.input} result=${event.result}/>
      <${TranscriptView}
        name="Transcript"
        evalEvents=${event.events}
      />
    </${EventPanel}>`;
};

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").Input2} props.input - The event object to display.
 * @param {import("../../types/log").Result} props.result - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
const SubtaskSummary = ({ input, result }) => {
  result = typeof result === "object" ? result : { result };
  return html` <div
    style=${{
      display: "grid",
      gridTemplateColumns:
        "minmax(0,max-content) max-content minmax(0,max-content)",
      columnGap: "1em",
    }}
  >
    <div>Input</div>
    <div></div>
    <div>Output</div>
    <${Rendered} values=${input} />
    <div><i class="${ApplicationIcons.arrows.right}" /></div>
    <${Rendered} values=${result} />
  </div>`;
};

const Rendered = ({ values }) => {
  if (Array.isArray(values)) {
    return values.map((val) => {
      return html`<${Rendered} values=${val} />`;
    });
  } else if (values && typeof values === "object") {
    return html`<${MetaDataView} entries=${values} />`;
  } else {
    return values;
  }
};
