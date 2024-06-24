import { html } from "htm/preact";
import { icons } from "../Constants.mjs";

export const CardHeader = ({ id, icon, label, classes, style, children }) => {
  return html`<div class="card-header ${classes || ""}" ...${{ id, style }}>
    ${icon
      ? html`<i
          class="${icon}"
          style=${{
            paddingRight: "0.2rem",
          }}
        ></i>`
      : ""}
    ${label ? label : ""} ${children}
  </div> `;
};

export const CardBody = ({ id, classes, style, children }) => {
  return html`<div class="card-body ${classes || ""}" ...${{ id, style }}>
    ${children}
  </div>`;
};

export const Card = ({ id, classes, style, children }) => {
  return html`
    <div class="card ${classes || ""}" ...${{ id, style }}>${children}</div>
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
            fontSize: "0.7rem",
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
          fontSize: "0.8rem",
        }}>
            <i class="${icons["toggle-right"]} toggle-rotated"></i>
        </div>
      </div>

      </${CardHeader}>
      `;
};
