//@ts-check
import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";

/**
 * Renders the ToolCallView component.
 *
 * @param {Object} props - The parameters for the component.
 * @param { string } props.logDir - The status of the listing
 *
 * @returns {import("preact").JSX.Element} The SampleTranscript component.
 */
export const TaskBar = ({ logDir }) => {
  return html` <div
    style=${{
      backgroundColor: "var(--bs-light)",
      fontSize: FontSize.smaller,
      display: "flex",
      alignItems: "center",
      padding: "1em",
      borderBottom: "solid var(--bs-light-border-subtle) 1px",
    }}
  >
    <div>Log Directory: ${logDir}</div>
  </div>`;
};
