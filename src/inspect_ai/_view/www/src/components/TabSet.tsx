import clsx from "clsx";
import {
  Children,
  Fragment,
  isValidElement,
  MouseEvent,
  ReactElement,
  useCallback,
  useEffect,
  useRef,
} from "react";
import moduleStyles from "./TabSet.module.css";

interface TabSetProps {
  id: string;
  type?: "tabs" | "pills";
  className?: string | string[];
  tabPanelsClassName?: string | string[];
  tabControlsClassName?: string | string;
  tools?: React.ReactNode;
  children:
    | ReactElement<TabPanelProps>
    | (ReactElement<TabPanelProps> | null | undefined)[];
}

interface TabPanelProps {
  id: string;
  index?: number;
  selected?: boolean;
  style?: React.CSSProperties;
  scrollable?: boolean;
  scrollRef?: React.RefObject<HTMLDivElement | null>;
  className?: string | string[];
  scrollPosition?: number;
  setScrollPosition?: (position: number) => void;
  children?: React.ReactNode;
  title: string;
  icon?: string;
  onSelected: (e: MouseEvent<HTMLElement>) => void;
}

export const TabSet: React.FC<TabSetProps> = ({
  id,
  type = "tabs",
  className,
  tabPanelsClassName,
  tabControlsClassName,
  tools,
  children,
}) => {
  const validTabs = flattenChildren(children);
  if (validTabs.length === 0) return null;

  return (
    <Fragment>
      <ul
        id={id}
        className={clsx("nav", `nav-${type}`, className, moduleStyles.tabs)}
        role="tablist"
        aria-orientation="horizontal"
      >
        {validTabs.map((tab, index) => (
          <Tab
            key={tab.props.id}
            index={index}
            type={type}
            tab={tab}
            className={tabControlsClassName}
          />
        ))}
        {tools && <TabTools tools={tools} />}
      </ul>
      <TabPanels id={id} tabs={validTabs} className={tabPanelsClassName} />
    </Fragment>
  );
};

// Individual Tab Component
const Tab: React.FC<{
  type?: "tabs" | "pills";
  tab: React.ReactElement<TabPanelProps>;
  index: number;
  className?: string | string[];
}> = ({ type = "tabs", tab, index, className }) => {
  const tabId = tab.props.id || computeTabId("tabset", index);
  const tabContentsId = computeTabContentsId(tab.props.id);
  const isActive = tab.props.selected;

  return (
    <li role="presentation" className={clsx("nav-item", moduleStyles.tabItem)}>
      <button
        id={tabId}
        className={clsx(
          "nav-link",
          className,
          isActive && "active",
          type === "pills" ? moduleStyles.pill : moduleStyles.tab,
          "text-size-small",
          "text-style-label",
        )}
        type="button"
        role="tab"
        aria-controls={tabContentsId}
        aria-selected={isActive}
        onClick={(e) => tab.props.onSelected(e)}
      >
        {tab.props.icon && (
          <i className={clsx(tab.props.icon, moduleStyles.tabIcon)} />
        )}
        {tab.props.title}
      </button>
    </li>
  );
};

// Tab Panels Container
const TabPanels: React.FC<{
  id: string;
  tabs: React.ReactElement<TabPanelProps>[];
  className?: string | string[];
}> = ({ id, tabs, className }) => (
  <div className={clsx("tab-content", className)} id={`${id}-content`}>
    {tabs.map((tab, index) => (
      <TabPanel key={tab.props.id} {...tab.props} index={index} />
    ))}
  </div>
);

// Individual Tab Panel
export const TabPanel: React.FC<TabPanelProps> = ({
  id,
  selected,
  style,
  scrollable = true,
  scrollRef,
  className,
  scrollPosition,
  setScrollPosition,
  children,
}) => {
  const tabContentsId = computeTabContentsId(id);
  const tabContentsRef = scrollRef || useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!selected || scrollPosition === undefined || !tabContentsRef.current)
      return;

    const observer = new MutationObserver(() => {
      if (tabContentsRef.current) {
        tabContentsRef.current.scrollTop = scrollPosition;
      }
      observer.disconnect(); // Stop observing after first content load
    });

    observer.observe(tabContentsRef.current, {
      childList: true,
      subtree: true,
    });

    return () => observer.disconnect();
  }, []);

  // Handle scrolling
  const onScroll = useCallback(
    (e: React.UIEvent<HTMLDivElement>) => {
      if (setScrollPosition) {
        setScrollPosition(e.currentTarget.scrollTop);
      }
    },
    [setScrollPosition],
  );

  return (
    <div
      id={tabContentsId}
      ref={tabContentsRef}
      className={clsx(
        "tab-pane",
        selected && "show active",
        className,
        moduleStyles.tabContents,
        scrollable && moduleStyles.scrollable,
      )}
      style={style}
      onScroll={onScroll}
    >
      {children}
    </div>
  );
};

// Tab Tools Component
const TabTools: React.FC<{ tools?: React.ReactNode }> = ({ tools }) => (
  <div className={clsx("tab-tools", moduleStyles.tabTools)}>{tools}</div>
);

// Utility functions
const computeTabId = (id: string, index: number) => `${id}-${index}`;
const computeTabContentsId = (id: string) => `${id}-contents`;

const flattenChildren = (
  children: React.ReactNode,
): ReactElement<TabPanelProps>[] => {
  return Children.toArray(children).flatMap((child) => {
    if (isValidElement(child)) {
      const element = child as React.ReactElement<any>;

      if (element.type === Fragment) {
        return flattenChildren(element.props.children);
      }
      return element;
    }
    return [];
  });
};
