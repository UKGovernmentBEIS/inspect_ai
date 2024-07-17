// @ts-check
import { html } from "htm/preact";
import { ApplicationIcons } from "../appearance/Icons.mjs";

/**
 * @typedef {Object} CopyButtonProps
 * @property {string} value - The text value to be copied to the clipboard.
 */

/**
 * CopyButton component.
 * @param {CopyButtonProps} props - The props object.
 * @returns {import("preact").JSX.Element} The CopyButton component.
 */
export const CopyButton = ({ value }) => {
  return html`<button
    class="copy-button"
    style=${{
      border: "none",
      backgroundColor: "inherit",
      opacity: "0.5",
      paddingTop: "0px",
    }}
    data-clipboard-text=${value}
    onclick=${(e) => {
      const iEl = e.target;
      if (iEl) {
        iEl.className = `${ApplicationIcons.confirm} primary`;
        setTimeout(() => {
          iEl.className = ApplicationIcons.copy;
        }, 1250);
      }
      return false;
    }}
  >
    <i class=${ApplicationIcons.copy}></i>
  </button>`;
};
