import { html } from "htm/preact";

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
        fontSize: "0.5rem",
        textTransform: "uppercase",
        fontWeight: "600",
        marginBottom: "-0.2rem",
        color: "var(--bs-secondary)",
      }}
    >
      ${label}
    </div>
    <div style=${{ fontSize: "0.8rem", ...valueStyle }}>${children}</div>
  </div>`;
};
