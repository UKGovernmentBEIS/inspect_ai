import { html } from "htm/preact";

export const SampleGroupSeparator = ({ label, group }) => {
  return html`<div
    style=${{
      backgroundColor: "var(--bs-secondary-bg)",
      padding: ".45em 1em .25em 1em",
      textTransform: "uppercase",
      color: "var(--bs-secondary)",
      fontSize: "0.8em",
      fontWeight: 600,
      borderBottom: "solid 1px var(--bs-border-color)",
    }}
  >
    <div>${label} ${group}</div>
  </div>`;
};
