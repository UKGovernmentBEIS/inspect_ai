import { html } from "htm/preact";
import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize, TextStyle } from "../appearance/Fonts.mjs";

export const CardHeader = ({ id, icon, label, classes, style, children }) => {
  return html`<div
    class="${classes || ""}"
    ...${{ id }}
    style=${{
      display: "grid",
      gridTemplateColumns: "max-content auto",
      columnGap: "0em",
      padding: "0.5em 0.5em 0.5em 0.5em",
      fontSize: FontSize.small,
      fontWeight: 600,
      ...TextStyle.label,
      ...style,
    }}
  >
    ${icon
      ? html`<i
          class="${icon}"
          style=${{
            paddingRight: "0.2rem",
          }}
        ></i>`
      : html`<span
          style=${{
            paddingRight: "0.2rem",
          }}
        ></span>`}
    ${label ? label : ""} ${children}
  </div> `;
};

export const CardBody = ({ id, classes, style, children }) => {
  return html`<div
    class="${classes || ""}"
    ...${{ id }}
    style=${{
      backgroundColor: "var(--bs-body-bg)",
      border: "solid 1px var(--bs-light-border-subtle)",
      borderRadius: "var(--bs-border-radius)",
      margin: "0 8px 8px 8px",
      padding: "0.5em",
      ...style,
    }}
  >
    ${children}
  </div>`;
};

export const Card = ({ id, classes, style, children }) => {
  return html`
    <div
      class="${classes || ""}"
      ...${{ id }}
      style=${{
        backgroundColor: "var(--bs-light-bg-subtle)",
        border: "solid 1px var(--bs-light-border-subtle)",
        borderRadius: "var(--bs-border-radius)",
        marginBottom: "1.5em",
        ...style,
      }}
    >
      ${children}
    </div>
  `;
};

export const CardCollapsingHeader = ({
  id,
  icon,
  label,
  cardBodyId,
  children,
}) => {
  return html`
  <${CardHeader} id=${id} classes="container-fluid collapse show do-not-collapse-self" style=${{
    borderBottom: "none",
  }}>
      <div class="row row-cols-3" 
        type="button"
        data-bs-toggle="collapse"
        data-bs-target="#${cardBodyId}"
        aria-expanded="false"
        aria-controls="${cardBodyId}"
        style=${{
          justifyContent: "space-between",
          alignItems: "center",
        }}>
        <div style=${{ flex: "0 0 content", paddingRight: "0.5rem" }}>
          <i class="${icon}"></i> <span class="hide-when-collapsed">${label}</span>
        </div>
        <div
          class="hide-when-expanded"
          style=${{
            color: "var(--body-color)",
            opacity: "0.8",
            flex: "1 1 auto",
            fontSize: FontSize.smaller,
            paddingRight: "0",
            paddingLeft: "0",
            transition: "opacity 0.2s ease-out",
            display: "flex",
            justifyContent: "space-between",
          }}
        >

        
        ${children}
          
        </div>
        <div style=${{
          flex: "0 1 1em",
          textAlign: "right",
          padding: "0 0.5em 0.1em 0.5em",
          fontSize: FontSize.smaller,
        }}>
            <i class="${ApplicationIcons["toggle-right"]} toggle-rotated"></i>
        </div>
      </div>

      </${CardHeader}>
      `;
};
