// @ts-check
import { html } from "htm/preact";
import { useCallback, useState } from "preact/hooks";
import { ApplicationIcons } from "../../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../../appearance/Fonts.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string | undefined} props.title - The name of the event
 * @param {string | undefined} props.icon - The name of the event
 * @param {"normal"|"compact"} props.style - The style of the display
 * @param {boolean | undefined} props.collapse - Whether to collapse this entry
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventPanel = ({ title, icon, style, collapse, children }) => {
  /**
   * State hook for managing the collapsed state.
   *
   * @type {[boolean|undefined, (value: boolean|undefined) => void]}
   */
  const [collapsed, setCollapsed] = useState(collapse);
  const onCollapse = useCallback(() => {
    setCollapsed(!collapsed);
  }, [collapsed, setCollapsed]);

  style = style || "normal";
  const titleEl = title
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
        <div>${style === "compact" ? children : ""}</div>
      </div>`
    : "";

  const card = html` <div
    class="card"
    style=${{
      padding: style === "normal" ? "0.5em" : "0.1em 0.5em",
      marginBottom: "-1px",
    }}
  >
    ${titleEl}
    ${style === "normal"
      ? html`<div class="card-body" style=${{ padding: 0, marginLeft: "2em" }}>
          ${children}
        </div>`
      : ""}
  </div>`;

  return card;
};
