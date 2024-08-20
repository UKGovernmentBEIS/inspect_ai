import { html } from "htm/preact";
import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

export const ErrorPanel = ({ id, classes, title, error }) => {
  const emptyStyle = {
    display: "flex",
    flex: "0 0 content",
    alignItems: "center",
    justifyContent: "center",
  };
  const message = error.message;
  const stack = error.stack;
  return html`
    <div
      ...${{ id }}
      class="${classes ? classes : ""}"
      style=${{
        ...emptyStyle,
        flexDirection: "column",
        minHeight: "10rem",
        marginTop: "4rem",
      }}
    >
      <div style=${{ ...emptyStyle, fontSize: FontSize["title-secondary"] }}>
        <div>
          <i
            class="${ApplicationIcons.error}"
            style="${{ marginRight: "0.5rem", color: "var(--bs-red)" }}"
          ></i>
        </div>
        <div>${title || ""}</div>
      </div>
      <div
        style=${{
          display: "inline-block",
          fontSize: FontSize.smaller,
          marginTop: "3rem",
          border: "solid 1px var(--bs-border-color)",
          borderRadius: "var(--bs-border-radius)",
          padding: "1em",
          maxWidth: "80%",
        }}
      >
        <div>
          Error: ${message || ""}
          ${stack &&
          html`
            <pre style=${{ fontSize: FontSize.smaller }}>
            <code>
              at ${stack}
            </code>
          </pre>
          `}
        </div>
      </div>
    </div>
  `;
};
