import { html } from "htm/preact";

export const EmptyPanel = ({ id, classes, height, style, children }) => {
  const emptyStyle = {
    display: "flex",
    textAlign: "center",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center",
    height: height ? height : "10rem",
  };
  return html`
    <div
      ...${{ id }}
      class="${classes ? classes : ""}"
      style=${{ width: "100%" }}
    >
      <div style=${{ ...emptyStyle, ...style }}>
        <div>${children || ""}</div>
      </div>
    </div>
  `;
};
