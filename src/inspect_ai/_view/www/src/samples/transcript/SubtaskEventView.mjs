// @ts-check
import { html } from "htm/preact";
import { TranscriptView } from "./TranscriptView.mjs";
import { EventPanel } from "./EventPanel.mjs";
import { MetaDataView } from "../../components/MetaDataView.mjs";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param { Object } props.style - The style of this event.
 * @param {import("../../types/log").SubtaskEvent} props.event - The event object to display.
 * @param {import("./Types.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @param { Object } props.depth - The depth of this event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SubtaskEventView = ({ id, event, style, stateManager, depth }) => {
  return html`
    <${EventPanel} id=${id} title="Subtask: ${event.name}" icon=${ApplicationIcons.subtask} style=${style}>
      <${SubtaskSummary} name="Summary"  input=${event.input} result=${event.result}/>
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
    </${EventPanel}>`;
};

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").Input2} props.input - The event object to display.
 * @param {import("../../types/log").Result1} props.result - The event object to display.
 * @returns {import("preact").JSX.Element} The component.
 */
const SubtaskSummary = ({ input, result }) => {
  result = typeof result === "object" ? result : { result };
  return html` <div
    style=${{
      display: "grid",
      gridTemplateColumns: "minmax(0, 1fr) max-content minmax(0, 1fr)",
      columnGap: "1em",
      margin: "0.5em 0",
    }}
  >
    <div style=${{ ...TextStyle.label }}>Input</div>
    <div style=${{ fontSize: FontSize.large, padding: "0 2em" }}></div>
    <div style=${{ ...TextStyle.label }}>Output</div>
    <${Rendered} values=${input} />
    <div style=${{ fontSize: FontSize["title-secondary"], padding: "0 2em" }}>
      <i class="${ApplicationIcons.arrows.right}" />
    </div>
    <${Rendered} values=${result} />
  </div>`;
};

/**
 * Recursively renders content based on the type of `values`.
 *
 * @param {Object} props - The component props.
 * @param {Array<unknown>|Object|string|number} props.values - The values to be rendered. Can be an array, object, string, or number.
 * @returns {import("preact").JSX.Element|Array<import("preact").JSX.Element>|string|number} The rendered content, which can be a JSX element, an array of JSX elements, or a primitive value.
 */
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
