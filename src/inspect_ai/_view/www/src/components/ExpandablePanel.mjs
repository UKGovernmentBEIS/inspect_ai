import { html } from "htm/preact";
import { useEffect, useRef, useState } from "preact/hooks";

import { icons, sharedStyles } from "../Constants.mjs";

export const ExpandablePanel = ({ collapse, border, lines = 7, children }) => {
  const [collapsed, setCollapsed] = useState(collapse);
  const [showToggle, setShowToggle] = useState(false);

  const contentsRef = useRef();
  const observerRef = useRef();

  // Ensure that when content changes, we reset the collapse state.
  useEffect(() => {
    setCollapsed(collapse);
  }, [children, collapse]);

  // Determine whether we should show the toggle
  useEffect(() => {
    const checkScrollable = () => {
      if (collapse && contentsRef.current) {
        const isScrollable =
          contentsRef.current.offsetHeight < contentsRef.current.scrollHeight;
        setShowToggle(isScrollable);
      }
    };

    // When an entry is visible, check to see whether it is scrolling
    observerRef.current = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          checkScrollable();
        }
      });
    });

    if (contentsRef.current) {
      observerRef.current.observe(contentsRef.current);
    }

    // Initial check
    checkScrollable();

    return () => {
      if (observerRef.current && contentsRef.current) {
        observerRef.current.unobserve(contentsRef.current);
      }
    };
  }, [collapse, contentsRef, observerRef]);

  // Enforce the line clamp if need be
  let contentsStyle = { fontSize: "0.8rem" };
  if (collapse && collapsed) {
    contentsStyle = { ...contentsStyle, ...sharedStyles.lineClamp(lines) };
  }

  if (border) {
    contentsStyle.border = "solid var(--bs-light-border-subtle) 1px";
  }

  return html`<div
      class="expandable-panel"
      ref=${contentsRef}
      style=${contentsStyle}
    >
      ${children}
    </div>
    ${showToggle
      ? html`<${MoreToggle}
          collapsed=${collapsed}
          setCollapsed=${setCollapsed}
          border=${!border}
        />`
      : ""}`;
};

const MoreToggle = ({ collapsed, border, setCollapsed }) => {
  const text = collapsed ? "more" : "less";
  const icon = collapsed ? icons["expand-down"] : icons["collapse-up"];

  const topStyle = {
    display: "flex",
    marginBottom: "0.5em",
  };

  if (border) {
    topStyle.borderTop = "solid var(--bs-light-border-subtle) 1px";
    topStyle.marginTop = "0.5em";
  } else {
    topStyle.marginTop = "0";
  }

  return html`
    <div style=${topStyle}>
      <div
        style=${{
          display: "inline-block",
          border: "solid var(--bs-light-border-subtle) 1px",
          borderTop: "none",
          marginLeft: "auto",
          marginRight: "1em",
        }}
      >
        <button
          class="btn"
          style=${{
            fontSize: "0.7rem",
            border: "none",
            padding: "0.1rem .5rem",
          }}
          onclick=${() => {
            setCollapsed(!collapsed);
          }}
        >
          <i class="${icon}" /> ${text}
        </button>
      </div>
    </div>
  `;
};
