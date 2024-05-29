import { html } from "htm/preact";

export const DialogButton = ({ id, btnType, classes, style, children }) => {
  return html`<button
    type="button"
    class="btn ${btnType ? btnType : ""} ${classes ? classes : ""}"
    data-bs-toggle="modal"
    data-bs-target="#${id}"
    ...${{ style }}
  >
    ${children}
  </button>`;
};

export const DialogAfterBody = ({
  id,
  title,
  classes,
  scrollable,
  centered,
  styles,
  children,
}) => {
  return html`
    <div
      class="modal fade ${classes}"
      id="${id}"
      tabindex="0"
      aria-hidden="true"
      styles=${{ ...styles }}
    >
      <div
        class="modal-dialog modal-lg ${centered
          ? "modal-dialog-centered"
          : ""} ${scrollable ? "modal-dialog-scrollable" : ""}"
      >
        <div class="modal-content">
          <div class="modal-header">
            <h5 class="modal-title">${title}</h5>
            <button
              type="button"
              class="btn-close"
              data-bs-dismiss="modal"
              aria-label="Close"
            ></button>
          </div>
          <div class="modal-body">${children}</div>
          <div class="modal-footer">
            <button
              type="button"
              class="btn btn-outline-secondary"
              data-bs-dismiss="modal"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  `;
};
