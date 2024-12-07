import { html } from "htm/preact";
import { useCallback, useEffect, useRef, useState } from "preact/hooks";

import { ApplicationIcons } from "../appearance/Icons.mjs";
import { FontSize } from "../appearance/Fonts.mjs";

export const ExpandablePanel = ({
  collapse,
  border,
  lines = 15,
  style,
  children,
}) => {
  const [collapsed, setCollapsed] = useState(collapse);
  const [showToggle, setShowToggle] = useState(false);

  const contentsRef = useRef();
  const observerRef = useRef();

  // Ensure that when content changes, we reset the collapse state.
  useEffect(() => {
    setCollapsed(collapse);
  }, [children, collapse]);

  const refreshCollapse = useCallback(() => {
    if (collapse && contentsRef.current) {
      const isScrollable =
        contentsRef.current.offsetHeight < contentsRef.current.scrollHeight;
      setShowToggle(isScrollable);
    }
  }, [collapse, setShowToggle, contentsRef]);

  useEffect(() => {
    refreshCollapse();
  }, [children]);

  // Determine whether we should show the toggle
  useEffect(() => {
    // When an entry is visible, check to see whether it is scrolling
    observerRef.current = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          refreshCollapse();
        }
      });
    });

    if (contentsRef.current) {
      observerRef.current.observe(contentsRef.current);
    }

    return () => {
      if (observerRef.current && contentsRef.current) {
        observerRef.current.unobserve(contentsRef.current);
      }
    };
  }, [contentsRef, observerRef]);

  // Enforce the line clamp if need be
  let contentsStyle = { fontSize: FontSize.base };
  if (collapse && collapsed) {
    contentsStyle = {
      ...contentsStyle,
      maxHeight: `${lines}em`,
      overflow: "hidden",
    };
  }

  if (border) {
    contentsStyle.border = "solid var(--bs-light-border-subtle) 1px";
  }

  if (!showToggle) {
    contentsStyle.marginBottom = "1em";
  }

  return html`<div
      class="expandable-panel"
      ref=${contentsRef}
      style=${{ ...contentsStyle, ...style }}
    >
      ${children}
    </div>
    ${showToggle
      ? html`<${MoreToggle}
          collapsed=${collapsed}
          setCollapsed=${setCollapsed}
          border=${!border}
          style=${style}
        />`
      : ""}`;
};

const MoreToggle = ({ collapsed, border, setCollapsed, style }) => {
  const text = collapsed ? "more" : "less";
  const icon = collapsed
    ? ApplicationIcons["expand-down"]
    : ApplicationIcons.collapse.up;

  const topStyle = {
    display: "flex",
    marginBottom: "0.5em",
    ...style,
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
            fontSize: FontSize.smaller,
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
