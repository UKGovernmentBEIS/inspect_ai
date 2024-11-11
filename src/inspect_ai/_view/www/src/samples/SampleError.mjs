//@ts-check
import { html } from "htm/preact";

import { FontSize } from "../appearance/Fonts.mjs";
import { ApplicationIcons } from "../appearance/Icons.mjs";
import { ApplicationStyles } from "../appearance/Styles.mjs";

/**
 * Component to display a styled error message.
 *
 * @param {Object} props - The component properties.
 * @param {string} [props.message] - The error message
 * @param {string} [props.align="center"] - The alignment for the error message. Defaults to "center".
 * @param {Object} [props.style] - Styles to add for this component
 * @returns {import("preact").JSX.Element} The error component.
 */
export const SampleError = ({ message, align, style }) => {
  align = align || "center";

  return html`<div
    style=${{
      color: "var(--bs-danger)",
      display: "grid",
      gridTemplateColumns: "1fr",
      alignContent: align,
      justifyItems: "center",
      ...style,
    }}
  >
    <i
      class=${ApplicationIcons.error}
      style=${{
        fontSize: FontSize.small,
        lineHeight: FontSize.small,
        height: FontSize.small,
      }}
    />
    <div style=${{ maxWidth: "300px", ...ApplicationStyles.lineClamp(2) }}>
      ${errorType(message)}
    </div>
  </div>`;
};

/**
 * Component to display a styled error message.
 *
 * @param {Object} props - The component properties.
 * @param {string} [props.message] - The message to display
 * @param {Object} [props.style] - Styles to add for this component
 * @returns {import("preact").JSX.Element} The error component.
 */
export const FlatSampleError = ({ message, style }) => {
  return html`<div
    style=${{
      color: "var(--bs-danger)",
      display: "grid",
      gridTemplateColumns: "max-content max-content",
      columnGap: "0.2em",
      ...style,
    }}
  >
    <i
      class=${ApplicationIcons.error}
      style=${{
        fontSize: FontSize.base,
        lineHeight: FontSize.base,
        height: FontSize.base,
      }}
    />
    <div
      style=${{
        fontSize: FontSize.base,
        lineHeight: FontSize.base,
        height: FontSize.base,
      }}
    >
      ${errorType(message)}
    </div>
  </div>`;
};

/**
 * Extracts the error type from a given message.
 * If the message contains parentheses, it returns the substring before the first parenthesis.
 * Otherwise, it returns "Error".
 *
 * @param {string | undefined} message - The error message from which to extract the type.
 * @returns {string} The extracted error type or "Error" if not found.
 */
const errorType = (message) => {
  if (!message) {
    return "Error";
  }

  if (message.includes("(")) {
    return message.split("(")[0];
  }
  return "Error";
};
