import { html } from "htm/preact";
import { icons } from "../Constants.mjs";

export const CopyButton = ({ value }) => {
  return html`<button
    class="copy-button"
    style=${{ border: "none", backgroundColor: "inherit", opacity: "0.5" }}
    data-clipboard-text=${value}
    onclick=${(e) => {
      const iEl = e.target;
      if (iEl) {
        iEl.className = `${icons.confirm} primary`;
        setTimeout(() => {
          iEl.className = icons.copy;
        }, 1250);
      }
      return false;
    }}
  >
    <i class=${icons.copy}></i>
  </button>`;
};
