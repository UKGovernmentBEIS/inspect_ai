// @ts-check
import { html } from "htm/preact";
import { useCallback, useState } from "preact/hooks";
import { ApplicationIcons } from "../../appearance/Icons.mjs";

/**
 * Renders the StateEventView component.
 *
 * @param {Object} props - The properties passed to the component.
 * @param {string} props.name - The name of the event
 * @param {boolean | undefined} props.collapse - Whether to collapse this entry
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element[]} The component.
 */
export const TranscriptEvent = ({ name, collapse, children }) => {
  /**
   * State hook for managing the collapsed state.
   *
   * @type {[boolean|undefined, (value: boolean|undefined) => void]}
   */
  const [collapsed, setCollapsed] = useState(collapse);
  const onCollapse = useCallback(() => {
    setCollapsed(!collapsed);
  }, [collapsed, setCollapsed]);

  const contents = [];
  if (name) {
    contents.push(
      html`<${TranscriptEventTitle}
        title=${name}
        collapse=${collapse}
        onCollapse=${onCollapse}
      />`,
    );
  }

  contents.push(
    html`<div>
      <div
        style=${collapsed !== undefined
          ? collapsed
            ? { height: 0, overflowY: "hidden" }
            : {}
          : {}}
      >
        ${children}
      </div>
    </div>`,
  );
  return contents;
};

export const TranscriptEventTitle = ({ title, collapse, onCollapse }) => {
  return html`
    <div
      style=${{
        textTransform: "uppercase",
        fontSize: "0.7rem",
        cursor: "pointer",
      }}
    >
      ${title}
      ${collapse !== undefined
        ? html`
            <button
              class="btn"
              style=${{
                fontSize: "0.7rem",
                border: "none",
                padding: "0.1rem .5rem",
              }}
              onclick=${onCollapse}
            >
              <i
                class="${collapse
                  ? ApplicationIcons.caret.right
                  : ApplicationIcons.caret.down}"
              />
            </button>
          `
        : ""}
    </div>
  `;
};
