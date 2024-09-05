import { html } from "htm/preact";
import { useState } from "preact/hooks";

import { FontSize } from "../appearance/Fonts.mjs";

import { ApplicationIcons } from "../appearance/Icons.mjs";

export const WarningBand = ({ message }) => {
  const [hidden, setHidden] = useState(false);

  return html`
    <div
      style=${{
        gridTemplateColumns: "max-content auto max-content",
        alignItems: "center",
        columnGap: "0.5em",
        fontSize: FontSize.small,
        color: "var(--bs-warning-text-emphasis)",
        background: "var(--bs-warning-bg-subtle)",
        borderBottom: "solid 1px var(--bs-light-border-subtle)",
        padding: "0.3em 1em",
        display: hidden ? "none" : "grid",
      }}
    >
      <i class=${ApplicationIcons.logging.warning} />
      ${message}
      <button
        title="Close"
        style=${{
          fontSize: FontSize["title-secondary"],
          margin: "0",
          padding: "0",
          color: "var(--bs-warning-text-emphasis)",
          height: FontSize["title-secondary"],
          lineHeight: FontSize["title-secondary"],
        }}
        class="btn"
        onclick=${() => {
          setHidden(true);
        }}
      >
        <i class=${ApplicationIcons.close}></i>
      </button>
    </div>
  `;
};
