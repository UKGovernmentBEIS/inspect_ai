import clsx from "clsx";
import { Fragment, MouseEvent, useCallback, useRef } from "react";
import moduleStyles from "./TabSet.module.css";

interface TabSetProps {
  id: string;
  type?: "tabs" | "pills";
  className?: string | string[];
  tabPanelsClassName?: string | string[];
  tabControlsClassName?: string | string;
  tools?: React.ReactNode;
  children: React.ReactElement<TabPanelProps>[];
}

interface TabPanelProps {
  id: string;
  index?: number;
  selected?: boolean;
  style?: React.CSSProperties;
  scrollable?: boolean;
  scrollRef?: React.RefObject<HTMLDivElement>;
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
  type,
  className,
  tabPanelsClassName,
  tabControlsClassName,
  tools,
  children,
}) => {
  // The tabs themselves
  const tabs = children;

  // Process the tab style
  const tabType = type || "tabs";

  // Render the tabs
  return (
    <Fragment>
      <ul
        id={id}
        class={clsx("nav", `nav-${tabType}`, className, moduleStyles.tabs)}
        role="tablist"
        aria-orientation="horizontal"
      >
        <Tabs
          tabs={tabs}
          type={tabType}
          className={clsx(tabControlsClassName)}
        />
        <TabTools tools={tools} />
      </ul>
      <TabPanels id={id} tabs={tabs} className={clsx(tabPanelsClassName)} />
    </Fragment>
  );
};

// Defines a tab panel that appears within the tabset
export const TabPanel: React.FC<TabPanelProps> = ({
  id,
  selected,
  style,
  scrollable,
  scrollRef,
  className,
  scrollPosition,
  setScrollPosition,
  children,
}) => {
  const tabContentsId = computeTabContentsId(id);
  const tabContentsRef = scrollRef || useRef(null);

  setTimeout(() => {
    if (
      scrollPosition !== undefined &&
      tabContentsRef.current &&
      tabContentsRef.current.scrollTop !== scrollPosition
    ) {
      tabContentsRef.current.scrollTop = scrollPosition;
    }
  }, 0);

  const onScroll = useCallback(
    (e: any) => {
      if (setScrollPosition) {
        setScrollPosition(e.srcElement.scrollTop);
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
        "show",
        selected ? "active" : undefined,
        className,
        moduleStyles.tabContents,
        scrollable === undefined || scrollable
          ? moduleStyles.scrollable
          : undefined,
      )}
      style={style}
      onScroll={onScroll}
    >
      {children}
    </div>
  );
};

// Render the tabs / pills themselves
const Tabs: React.FC<{
  tabs: React.ReactElement<TabPanelProps>[];
  type?: "tabs" | "pills";
  className?: string | string[];
}> = ({ tabs, type, className }) => {
  return tabs.map((tab, index) => {
    return (
      <Tab
        type={type || "tabs"}
        tab={tab}
        index={index}
        className={clsx(className)}
      />
    );
  });
};

// An individual tab
const Tab: React.FC<{
  type?: "tabs" | "pills";
  tab: React.ReactElement<TabPanelProps>;
  index: number;
  className?: string | string[];
}> = ({ type, tab, index, className }) => {
  const tabId = tab.props.id || computeTabId("tabset", index);
  const tabContentsId = computeTabContentsId(tab.props.id);
  const isActive = tab.props.selected;

  const tabClz = [moduleStyles.tab, "text-size-small", "text-style-label"];
  const pillClz: string[] = [];
  return (
    <li
      class="nav-item"
      role="presentation"
      className={clsx(moduleStyles.tabItem)}
    >
      <button
        id={tabId}
        className={clsx(
          className,
          "nav-link",
          isActive ? "active" : undefined,
          type === "pills" ? pillClz : tabClz,
        )}
        type="button"
        role="tab"
        aria-controls={tabContentsId}
        aria-selected={isActive ? true : false}
        onClick={(e) => {
          tab.props.onSelected(e);
          return false;
        }}
      >
        {tab.props.icon ? (
          <i className={clsx(tab.props.icon, moduleStyles.tabIcon)} />
        ) : (
          ""
        )}
        {tab.props.title}
      </button>
    </li>
  );
};

// The tools shown for the tab
const TabTools: React.FC<{ tools?: React.ReactNode }> = ({ tools }) => {
  return (
    <div className={clsx("tab-tools", moduleStyles.tabTools)}>{tools}</div>
  );
};

// Render the tab panels
const TabPanels: React.FC<{
  id: string;
  tabs: React.ReactElement<TabPanelProps>[];
  className?: string | string[];
}> = ({ id, tabs, className }) => {
  return (
    <div className={clsx("tab-content", className)} id={`${id}-content`}>
      {tabs.map((tab, index) => {
        tab.props.index = index;
        return tab;
      })}
    </div>
  );
};

const computeTabId = (id: string, index: number) => {
  return `${id}-${index}`;
};
const computeTabContentsId = (id: string) => {
  return `${id}-contents`;
};
