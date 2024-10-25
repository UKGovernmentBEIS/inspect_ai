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
      let iEl = e.target;
      // I haven't yet been able to consistently cause this, but
      // this issue https://github.com/UKGovernmentBEIS/inspect_ai/issues/717
      // does sometimes happen and when it does, the target element is the BUTTON
      // not the I. Since I can't reliably determine the cause, for now just band-aid
      // by getting the child in this case.
      if (iEl.tagName === "BUTTON") {
        iEl = iEl.firstChild;
      }
      console.log({ iEl });
      if (iEl) {
        if (iEl) {
          iEl.className = `${ApplicationIcons.confirm} primary`;
          setTimeout(() => {
            iEl.className = ApplicationIcons.copy;
          }, 1250);
        }
      }
      return false;
    }}
  >
    <i class=${ApplicationIcons.copy}></i>
  </button>`;
};
