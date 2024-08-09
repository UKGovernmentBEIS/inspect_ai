// @ts-check
import { html } from "htm/preact";
import { EventPanel } from "./EventPanel.mjs";
import { FontSize } from "../../appearance/Fonts.mjs";
import { TextStyle } from "../../appearance/Fonts.mjs";
import { MetaDataGrid } from "../../components/MetaDataGrid.mjs";

/**
 * Renders the SampleInitEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param { string  } props.id - The id of this event.
 * @param {import("../../types/log").SampleInitEvent} props.event - The event object to display.
 * @param {import("./TranscriptState.mjs").StateManager} props.stateManager - A function that updates the state with a new state object.
 * @returns {import("preact").JSX.Element} The component.
 */
export const SampleInitEventView = ({ id, event, stateManager }) => {
  // Rememember the state (so other event viewers can use
  // it as a baseline when applying their state updates)
  //@ts-ignore
  stateManager.setState(event.state);


  // sample
  // id
  // input
  // target

  // state
  // messages

  return html`
  <${EventPanel} id=${id} title="Sample Init" style=${{ marginLeft: "2em", marginBottom: "1em" }}>

    <div name="Sample">
      <${MetaDataGrid} entries=${event.sample}/>
    </div>

    <div name="State">
      <${MetaDataGrid} entries=${event.state}/>
    </div>
  </${EventPanel}>`;
};
