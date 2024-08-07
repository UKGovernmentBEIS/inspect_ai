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
 * @param {Object} props.stats - The stats for the event
 * @param {number} props.stats.steps - The child steps for this event
 * @param {number} props.stats.duration - The duration of this event
 * @param {Object} props.contents - The contents for the event
 * @param {import("preact").JSX.Element | undefined} props.contents.summary - The summary view for the event
 * @param {import("preact").JSX.Element | undefined} props.contents.detail - The detailed view for the event
 * @param {import("preact").JSX.Element | undefined} props.contents.raw - The raw view for the event
 * @param {boolean | undefined} props.collapse - Whether to collapse this entry
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The component.
 */
export const EventPanel = ({ title, stats, contents, collapse, children }) => {
  /**
   * State hook for managing the collapsed state.
   *
   * @type {[boolean|undefined, (value: boolean|undefined) => void]}
   */
  const [collapsed, setCollapsed] = useState(collapse);
  const onCollapse = useCallback(() => {
    setCollapsed(!collapsed);
  }, [collapsed, setCollapsed]);

  const titleEl = title
    ? html`<div
        class="card-title"
        style=${{ fontSize: FontSize.large, ...TextStyle.secondary }}
      >
        <i class=${ApplicationIcons.metadata} /> ${title}
      </div>`
    : "";

  const card = html` <div
    class="card"
    style=${{ padding: "0.5rem", marginBottom: "-1px" }}
  >
    ${titleEl}
    <div class="card-body" style=${{ padding: 0, margin: 0 }}>${children}</div>
  </div>`;

  return card;
};
