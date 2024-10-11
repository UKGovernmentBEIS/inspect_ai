// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the EventRow component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string | undefined} props.title - The name of the event
 * @param {string | undefined} props.icon - The name of the event
 * @param {Object} props.style - The style of the event
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventRow = ({ title, icon, style, children }) => {
  const contentEl = title
    ? html`<div
        style=${{
          marginLeft: "0.5em",
          display: "grid",
          gridTemplateColumns: "max-content max-content minmax(0, 1fr)",
          columnGap: "0.5em",
          fontSize: FontSize.small,
        }}
      >
        <i class=${icon || ApplicationIcons.metadata} />
        <div style=${{ ...TextStyle.label }}>${title}</div>
        <div>${children}</div>
      </div>`
    : "";

  const card = html` <div
    class="card"
    style=${{
      padding: "0.4em",
      marginBottom: "0.4em",
      border: "solid 1px var(--bs-light-border-subtle)",
      borderRadius: "var(--bs-border-radius)",
      ...style,
    }}
  >
    ${contentEl}
  </div>`;
  return card;
};
