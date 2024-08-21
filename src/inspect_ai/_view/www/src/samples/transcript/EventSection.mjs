// @ts-check
import { html } from "htm/preact";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the Event Section component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string | undefined} props.title - The name of the event
 * @param {Object | undefined} props.style - The name of the event
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventSection = ({ title, style, children }) => {
  return html`<div
    style=${{
      margin: "1em 0 0 0",
      ...style,
    }}
  >
    <div
      style=${{
        fontSize: FontSize.smaller,
        ...TextStyle.label,
        fontWeight: 600,
        paddingBottom: "0.3em",
      }}
    >
      ${title}
    </div>
    ${children}
  </div>`;
};
