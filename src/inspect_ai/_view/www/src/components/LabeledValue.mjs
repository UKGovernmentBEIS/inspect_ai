import { html } from "htm/preact";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";

export const LabeledValue = ({
  label,
  style,
  valueStyle,
  layout = "column",
  children,
}) => {
  const flexDirection = layout === "column" ? "column" : "row";

  return html` <div
    style=${{
      display: "flex",
      flexDirection,
      ...style,
    }}
  >
    <div
      style=${{
        fontSize: FontSize.smaller,
        marginBottom: "-0.2rem",
        ...TextStyle.secondary,
        ...TextStyle.label,
      }}
    >
      ${label}
    </div>
    <div style=${{ fontSize: FontSize.base, ...valueStyle }}>${children}</div>
  </div>`;
};
