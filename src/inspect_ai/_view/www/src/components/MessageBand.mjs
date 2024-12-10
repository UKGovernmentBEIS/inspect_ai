import { html } from "htm/preact";

import { FontSize } from "../appearance/Fonts.mjs";

import { ApplicationIcons } from "../appearance/Icons.mjs";

export const MessageBand = ({ message, hidden, setHidden, type }) => {
  const bgColor =
    type === "info" ? "var(--bs-light)" : "var(--bs-" + type + "-bg-subtle)";
  const color =
    "var(--bs-" + (type === "info" ? "secondary" : type) + "-text-emphasis)";

  return html`
    <div
      style=${{
        gridTemplateColumns: "max-content auto max-content",
        alignItems: "center",
        columnGap: "0.5em",
        fontSize: FontSize.small,
        color: color,
        background: bgColor,
        borderBottom: "solid 1px var(--bs-light-border-subtle)",
        padding: "0.3em 1em",
        display: hidden ? "none" : "grid",
      }}
    >
      <i class=${ApplicationIcons.logging[type]} />
      ${message}
      <button
        title="Close"
        style=${{
          fontSize: FontSize["title-secondary"],
          margin: "0",
          padding: "0",
          color: "var(--bs-" + type + "-text-emphasis)",
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
