import { html } from "htm/preact";
import { FontSize } from "../appearance/Fonts.mjs";

export const ProgressBar = ({ style, animating }) => {
  const emptyStyle = {
    display: "flex",
    textAlign: "center",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center",
    border: "none",
    padding: "0",
    background: "#FFFFFF00",
    fontSize: FontSize.smaller,
    zIndex: 1001,
    width: "100%",
    ...style,
  };

  const progressContainerStyle = {
    width: "100%",
    height: "4px",
    background: "none",
  };

  const progressBarStyle = {
    width: "5%",
    height: "2px",
  };

  return html`
    <div style=${emptyStyle} class="empty-message">
      <div
        class="progress"
        role="progressbar"
        aria-label="Basic example"
        aria-valuenow="25"
        aria-valuemin="0"
        aria-valuemax="100"
        style=${progressContainerStyle}
      >
        ${animating
          ? html`<div
              class="progress-bar left-to-right-animate"
              style=${progressBarStyle}
            ></div>`
          : ""}
      </div>
    </div>
  `;
};
