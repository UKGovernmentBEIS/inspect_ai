import { html } from "htm/preact";
import { useCallback, useEffect, useRef } from "preact/hooks";

import { FontSize } from "../appearance/Fonts.mjs";
import { ProgressBar } from "./ProgressBar.mjs";
import { MessageBand } from "./MessageBand.mjs";

export const LargeModal = (props) => {
  const {
    id,
    title,
    detail,
    detailTools,
    footer,
    onkeyup,
    visible,
    onHide,
    showProgress,
    children,
    initialScrollPositionRef,
    setInitialScrollPosition,
    warning,
    warningHidden,
    setWarningHidden,
  } = props;

  // The footer
  const modalFooter = footer
    ? html`<div class="modal-footer">${footer}</div>`
    : "";

  // Support restoring the scroll position
  // but only do this for the first time that the children are set
  const scrollRef = useRef();
  useEffect(() => {
    if (scrollRef.current) {
      setTimeout(() => {
        if (scrollRef.current.scrollTop !== initialScrollPositionRef?.current) {
          scrollRef.current.scrollTop = initialScrollPositionRef?.current;
        }
      }, 0);
    }
  }, []);

  const onScroll = useCallback(
    (e) => {
      setInitialScrollPosition(e.srcElement.scrollTop);
    },
    [setInitialScrollPosition],
  );

  // Capture header elements
  const headerEls = [];
  // The title
  headerEls.push(
    html`<div
      class="modal-title"
      style=${{ fontSize: FontSize.smaller, flex: "1 1 auto" }}
    >
      ${title || ""}
    </div>`,
  );

  // A centered text element with tools to the left and right
  if (detail) {
    headerEls.push(
      html`<div
        style=${{
          marginLeft: "auto",
          marginRight: "auto",
          display: "flex",
          flex: "1 1 auto",
          justifyContent: "center",
        }}
      >
        ${detailTools.left
          ? detailTools.left.map((tool) => {
              return html`<${TitleTool} ...${tool} />`;
            })
          : ""}
        <div
          style=${{
            fontSize: FontSize.smaller,
            display: "flex",
            alignItems: "center",
          }}
        >
          <div>${detail}</div>
        </div>
        ${detailTools.right
          ? detailTools.right.map((tool) => {
              return html`<${TitleTool} ...${tool} />`;
            })
          : ""}
      </div>`,
    );
  }

  // The close 'x'
  headerEls.push(html`<button
      type="button"
      class="btn btn-close-large-dialog"
      onclick=${() => {
        onHide();
      }}
      aria-label="Close"
      style=${{
        borderWidth: "0px",
        fontSize: FontSize.larger,
        fontWeight: "300",
        padding: "0em 0.5em",
        flex: 1,
        textAlign: "right",
      }}
    >
      <${HtmlEntity}>&times;</${HtmlEntity}>
    </button>`);

  return html`<div
    id=${id}
    class="modal"
    tabindex="0"
    role="dialog"
    onkeyup=${onkeyup}
    style=${{
      borderRadius: "var(--bs-border-radius)",
      display: visible ? "block" : "none",
    }}
    tabindex=${visible ? 0 : undefined}
  >
    <div
      class="modal-dialog modal-dialog-scrollable"
      style=${{
        maxWidth: "100%",
        marginLeft: "var(--bs-modal-margin)",
        marginRight: "var(--bs-modal-margin)",
      }}
      role="document"
    >
      <div class="modal-content" style=${{ height: "100%" }}>
        <div
          class="modal-header"
          style=${{ padding: "0 0 0 1em", display: "flex" }}
        >
          ${headerEls}
        </div>
        <${ProgressBar}
          animating=${showProgress}
          containerStyle=${{
            marginBottom: "-2px",
            backgroundColor: "var(--bs-body-bg)",
          }}
        />

        ${warning
          ? html`<${MessageBand}
              message=${warning}
              hidden=${warningHidden}
              setHidden=${setWarningHidden}
              type="warning"
            />`
          : ""}
        <div class="modal-body" ref=${scrollRef} onscroll=${onScroll}>
          ${children}
        </div>
        ${modalFooter}
      </div>
    </div>
  </div>`;
};

const HtmlEntity = ({ children }) =>
  html`<span dangerouslySetInnerHTML=${{ __html: children }} />`;

const TitleTool = ({ label, icon, enabled, onclick }) => {
  return html`<button
    type="button"
    class="btn btn-outline"
    aria-label=${label}
    onclick=${onclick}
    disabled=${!enabled}
    style=${{
      paddingTop: 0,
      paddingBottom: 0,
      border: "none",
      fontSize: FontSize.small,
    }}
  >
    <i class="${icon}" />
  </button>`;
};
