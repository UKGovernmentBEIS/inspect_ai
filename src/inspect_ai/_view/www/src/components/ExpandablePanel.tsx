import clsx from "clsx";
import {
  CSSProperties,
  FC,
  memo,
  ReactNode,
  useCallback,
  useRef,
  useState,
} from "react";
import { useCollapsedState } from "../state/hooks";
import { useResizeObserver } from "../utils/dom";
import styles from "./ExpandablePanel.module.css";

interface ExpandablePanelProps {
  id: string;
  collapse: boolean;
  border?: boolean;
  lines?: number;
  children?: ReactNode;
  className?: string | string[];
}

export const ExpandablePanel: FC<ExpandablePanelProps> = memo(
  ({ id, collapse, border, lines = 15, children, className }) => {
    const [collapsed, setCollapsed] = useCollapsedState(id, collapse);

    const [showToggle, setShowToggle] = useState(false);
    const baseFontSizeRef = useRef<number>(0);

    const checkOverflow = useCallback(
      (entry: ResizeObserverEntry) => {
        const element = entry.target as HTMLDivElement;

        // Calculate line height if we haven't yet
        if (baseFontSizeRef.current === 0) {
          const computedStyle = window.getComputedStyle(element);
          const rootFontSize = parseFloat(computedStyle.fontSize);
          baseFontSizeRef.current = rootFontSize;
        }
        const maxCollapsedHeight = baseFontSizeRef.current * lines;
        const contentHeight = element.scrollHeight;

        setShowToggle(contentHeight > maxCollapsedHeight);
      },
      [lines],
    );
    const contentRef = useResizeObserver(checkOverflow);

    const baseStyles = {
      overflow: "hidden",
      ...(collapsed && {
        maxHeight: `${lines}rem`,
      }),
    };

    return (
      <div className={clsx(className)}>
        <div
          style={baseStyles}
          ref={contentRef}
          className={clsx(
            styles.expandablePanel,
            collapsed ? styles.expandableCollapsed : undefined,
            border ? styles.expandableBordered : undefined,
            showToggle ? styles.padBottom : undefined,
          )}
        >
          {children}
          {showToggle && (
            <>
              <MoreToggle
                collapsed={collapsed}
                setCollapsed={setCollapsed}
                border={!border}
              />
            </>
          )}
        </div>
        {showToggle && <div className={clsx(styles.separator)}></div>}
      </div>
    );
  },
);

interface MoreToggleProps {
  collapsed: boolean;
  border: boolean;
  setCollapsed: (collapsed: boolean) => void;
  style?: CSSProperties;
}

const MoreToggle: FC<MoreToggleProps> = ({
  collapsed,
  border,
  setCollapsed,
  style,
}) => {
  const text = collapsed ? "more" : "less";
  const handleClick = useCallback(() => {
    setCollapsed(!collapsed);
  }, [setCollapsed, collapsed]);

  return (
    <div
      className={clsx(styles.moreToggle, border ? styles.bordered : undefined)}
      style={style}
    >
      <button
        className={clsx("btn", styles.moreToggleButton, "text-size-smallest")}
        onClick={handleClick}
      >
        {text}...
      </button>
    </div>
  );
};

export default ExpandablePanel;
