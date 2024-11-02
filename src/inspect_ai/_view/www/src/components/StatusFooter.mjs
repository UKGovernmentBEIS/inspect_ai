// @ts-check
import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";

/**
 * Renders the status footer component.
 *
 * @param {Object} props - The props for the StatusFooter component.
 * @param {boolean} props.spinner - Indicates if a spinner should be displayed.
 * @param {string} props.spinnerMessage - The message to be shown with the spinner.
 * @param {Array<{ icon: string, text: string }>} props.statusMessages - Array of status messages, each containing an icon and text.
 * @param {import("preact").ComponentChildren} props.children - The rendered event.
 * @returns {import("preact").JSX.Element} The rendered StatusFooter component.
 */
export const StatusFooter = ({
  spinner,
  spinnerMessage,
  statusMessages,
  children,
}) => {
  return html` <div
    style=${{
      borderTop: "solid var(--bs-light-border-subtle) 1px",
      background: "var(--bs-light-bg-subtle)",
      fontSize: FontSize.smaller,
      display: "grid",
      gridTemplateColumns: "1fr max-content 1fr",
      justifyContent: "end",
      alignContent: "end",
      padding: "0.5em 1em",
      minHeight: "2.5em",
    }}
  >
    <div>
      ${spinner ? html`<${ProgressSpinner} message=${spinnerMessage} />` : ""}
    </div>
    <div>${children}</div>
    <div
      style=${{
        display: "flex",
        justifyContent: "flex-end",
        alignItems: "center",
      }}
    >
      ${statusMessages
        ? statusMessages.map((msg) => {
            return html`<${StatusMessage} icon=${msg.icon} text=${msg.text} />`;
          })
        : ""}
    </div>
  </div>`;
};

/**
 * Renders a status message component.
 *
 * @param {Object} props - The props for the StatusMessage component.
 * @param {string} [props.icon] - The icon class to display.
 * @param {string} [props.text] - The text message to display.
 * @returns {import("preact").JSX.Element} The rendered StatusMessage component.
 */
export const StatusMessage = ({ icon, text }) => {
  if (icon && !text) {
    return html`<i class=${icon} />`;
  } else if (icon && text) {
    return html`<div
      style=${{
        display: "grid",
        gridTemplateColumns: "max-content max-content",
        columnGap: "0.5em",
      }}
    >
      <i class=${icon} />
      <div>${text}</div>
    </div>`;
  } else if (text) {
    return html`<div>${text}</div>`;
  }
  return html``;
};

/**
 * Renders a progress spinner component with an optional message.
 *
 * @param {Object} props - The props for the ProgressSpinner component.
 * @param {string} [props.message] - The message to display alongside the spinner.
 * @returns {import("preact").JSX.Element} The rendered ProgressSpinner component.
 */
export const ProgressSpinner = ({ message }) => {
  const spinner = html`<div
    class="spinner-border"
    role="status"
    style=${{
      "--bs-spinner-width": "0.9rem",
      "--bs-spinner-height": "0.9rem",
      "--bs-spinner-border-width": "0.15em",
      marginTop: ".1em",
    }}
  >
    <span class="visually-hidden">${message}</span>
  </div>`;

  if (message) {
    return html` <div
      style=${{
        display: "grid",
        gridTemplateColumns: "max-content max-content",
        columnGap: "0.5em",
      }}
    >
      ${spinner}
      <div>${message}</div>
    </div>`;
  } else {
    return spinner;
  }
};
