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
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventRow = ({ title, icon, children }) => {
  const contentEl = title
    ? html`<div
        style=${{
          paddingLeft: "0.5em",
          display: "grid",
          gridTemplateColumns: "max-content max-content minmax(0, 1fr)",
          columnGap: "0.5em",
          fontSize: FontSize.small,
        }}
      >
        <i
          class=${icon || ApplicationIcons.metadata}
          style=${{ ...TextStyle.secondary }}
        />
        <div style=${{ ...TextStyle.label, ...TextStyle.secondary }}>
          ${title}
        </div>
        <div>${children}</div>
      </div>`
    : "";

  const card = html` <div
    class="card"
    style=${{
      padding: "0.1em 0.5em",
      marginBottom: "-1px",
    }}
  >
    ${contentEl}
  </div>`;
  return card;
};
