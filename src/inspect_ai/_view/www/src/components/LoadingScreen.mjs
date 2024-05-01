import { html } from "htm/preact";

export const LoadingScreen = ({ id, classes, message }) => {
  const fullScreenStyle = {
    position: "absolute",
    top: "0",
    bottom: "0",
    right: "0",
    left: "0",
    display: "flex",
    justifyContent: "center",
    alignItems: "center",
    zIndex:1000
  }

  const emptyStyle = {
    display: "flex",
    textAlign: "center",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center",
  };
  return html`
    <div ...${{ id, class: classes, style: fullScreenStyle}}>
      <div style=${emptyStyle} class="empty-message">
          <div
            class="spinner-border"
            style=${{ display: "inline", marginRight: "0.5rem" }}
            role="status"
          >
        </div>
        ${message || "Loading..."}
      </div>
    </div>
  `;
};
