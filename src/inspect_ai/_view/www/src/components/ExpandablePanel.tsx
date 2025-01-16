import { useCallback, useEffect, useRef, useState } from "preact/hooks";

import clsx from "clsx";
import { ApplicationIcons } from "../appearance/icons";
import "./ExpandablePanel.css";

interface ExpandablePanelProps {
  collapse: boolean;
  border?: boolean;
  lines?: number;
  children?: React.ReactNode;
  style?: React.CSSProperties;
}

export const ExpandablePanel: React.FC<ExpandablePanelProps> = ({
  collapse,
  border,
  lines = 15,
  style,
  children,
}) => {
  const [collapsed, setCollapsed] = useState(collapse);
  const [showToggle, setShowToggle] = useState(false);

  const contentsRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<ResizeObserver | null>(null);

  // Ensure that when content changes, we reset the collapse state.
  useEffect(() => {
    setCollapsed(collapse);
    ``;
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

  const className = [];
  let contentsStyle = {};
  if (collapse && collapsed) {
    className.push("expandable-collapsed");
    contentsStyle = {
      maxHeight: `${lines}em`,
    };
  }

  if (border) {
    className.push("expandable-bordered");
  }

  if (!showToggle) {
    className.push("expandable-togglable");
  }

  return (
    <div>
      <div
        className={clsx("expandable-panel", className)}
        ref={contentsRef}
        style={{ ...contentsStyle, ...style }}
      >
        {children}
      </div>
      {showToggle ? (
        <MoreToggle
          collapsed={collapsed}
          setCollapsed={setCollapsed}
          border={!border}
          style={style}
        />
      ) : (
        ""
      )}
    </div>
  );
};

interface MoreToggleProps {
  collapsed: boolean;
  border: boolean;
  setCollapsed: (collapsed: boolean) => void;
  style?: React.CSSProperties;
}

const MoreToggle: React.FC<MoreToggleProps> = ({
  collapsed,
  border,
  setCollapsed,
  style,
}) => {
  const text = collapsed ? "more" : "less";
  const icon = collapsed
    ? ApplicationIcons["expand-down"]
    : ApplicationIcons.collapse.up;

  const topStyle = {
    ...style,
  };

  const className = [];
  if (border) {
    className.push("bordered");
  }

  return (
    <div className={clsx("more-toggle", className)} style={topStyle}>
      <div className={"more-toggle-container"}>
        <button
          className={"btn more-toggle-button"}
          onClick={() => {
            setCollapsed(!collapsed);
          }}
        >
          <i className={icon} />
          {text}
        </button>
      </div>
    </div>
  );
};
