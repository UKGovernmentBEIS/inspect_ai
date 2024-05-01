import { html } from "htm/preact";
import { h } from "preact";

export const ToolButton = ({ name, classes, icon, onclick, ...rest }) => {
  // Create the component (dynamically to forward attributes)
  const attr = {
    type: "button",
    class: `btn btn-tools ${classes || ""}`,
    onclick,
    ...rest,
  };
  const iconEl = icon
    ? html`<i class="${icon}" style=${{ marginRight: "0.5em" }}></i>`
    : "";
  return h("button", attr, html`${iconEl}${name}`);
};
