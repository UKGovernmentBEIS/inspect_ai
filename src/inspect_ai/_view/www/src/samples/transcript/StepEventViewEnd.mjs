// @ts-check
import { html } from "htm/preact";
import { formatTime } from "../../utils/Format.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {import("../../types/log").StepEvent} props.event - The event object to display.
 * * @param {Date} props.stepStartTime - The timestamp when this step started
 * @returns {import("preact").JSX.Element} The component.
 */
export const StepEventViewEnd = ({ event, stepStartTime }) => {
  const durationMs =
    new Date(event.timestamp).getTime() - stepStartTime.getTime();
  const durationSec = durationMs / 1000;

  return html`<div
    style=${{
      marginBottom: "2em",
      fontSize: FontSize.smaller,
      ...TextStyle.label,
      ...TextStyle.secondary
    }}
  >
  </div>`;
};
