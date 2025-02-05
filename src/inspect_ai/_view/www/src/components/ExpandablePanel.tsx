import clsx from "clsx";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApplicationIcons } from "../appearance/icons";
import { useResizeObserver } from "../utils/dom";
import "./ExpandablePanel.css";

interface ExpandablePanelProps {
  collapse: boolean;
  border?: boolean;
  lines?: number;
  children?: React.ReactNode;
  className?: string | string[];
}

export const ExpandablePanel: React.FC<ExpandablePanelProps> = ({
  collapse,
  border,
  lines = 15,
  children,
  className,
}) => {
  const [isCollapsed, setIsCollapsed] = useState(collapse);
  const [showToggle, setShowToggle] = useState(false);
  const lineHeightRef = useRef<number>(0);

  useEffect(() => {
    setIsCollapsed(collapse);
  }, [collapse]);

  const checkOverflow = useCallback(
    (entry: ResizeObserverEntry) => {
      const element = entry.target as HTMLDivElement;

      // Calculate line height if we haven't yet
      if (!lineHeightRef.current) {
        const computedStyle = window.getComputedStyle(element);
        lineHeightRef.current = parseInt(computedStyle.lineHeight) || 16; // fallback to 16px if can't get line height
      }

      const maxCollapsedHeight = lines * lineHeightRef.current;
      const contentHeight = element.scrollHeight;

      setShowToggle(contentHeight > maxCollapsedHeight);
    },
    [lines],
  );

  const contentRef = useResizeObserver(checkOverflow);

  const baseStyles = {
    overflow: "hidden",
    ...(isCollapsed && {
      maxHeight: `${lines}em`,
    }),
  };

  return (
    <div className={clsx(className)}>
      <div
        style={baseStyles}
        ref={contentRef}
        className={clsx(
          "expandable-panel",
          isCollapsed ? "expandable-collapsed" : undefined,
          border ? "expandable-bordered" : undefined,
        )}
      >
        {children}
      </div>

      {showToggle && (
        <MoreToggle
          collapsed={isCollapsed}
          setCollapsed={setIsCollapsed}
          border={!border}
        />
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

  return (
    <div className={`more-toggle ${border ? "bordered" : ""}`} style={style}>
      <div className="more-toggle-container">
        <button
          className="btn more-toggle-button"
          onClick={() => setCollapsed(!collapsed)}
        >
          <i className={icon} />
          {text}
        </button>
      </div>
    </div>
  );
};

export default ExpandablePanel;
