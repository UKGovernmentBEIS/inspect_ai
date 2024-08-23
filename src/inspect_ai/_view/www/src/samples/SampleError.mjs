//@ts-check
import { html } from "htm/preact";

import { FontSize } from "../appearance/Fonts.mjs";
import { ApplicationIcons } from "../appearance/Icons.mjs";

/**
 * Component to display a styled error message.
 *
 * @param {Object} props - The component properties.
 * @param {string} [props.align="center"] - The alignment for the error message. Defaults to "center".
 * @param {Object} [props.style] - Styles to add for this component
 * @returns {import("preact").JSX.Element} The error component.
 */
export const SampleError = ({ align, style }) => {
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
    <div>Error</div>
  </div>`;
};

/**
 * Component to display a styled error message.
 *
 * @param {Object} props - The component properties.
 * @param {Object} [props.style] - Styles to add for this component
 * @returns {import("preact").JSX.Element} The error component.
 */
export const FlatSampleError = ({ style }) => {
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
      Error
    </div>
  </div>`;
};
