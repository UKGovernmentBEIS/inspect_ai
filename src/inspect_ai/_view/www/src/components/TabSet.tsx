import clsx from "clsx";
import {
  Children,
  CSSProperties,
  FC,
  Fragment,
  isValidElement,
  MouseEvent,
  ReactElement,
  ReactNode,
  RefObject,
  useRef,
} from "react";
import { useStatefulScrollPosition } from "../state/scrolling";
import moduleStyles from "./TabSet.module.css";

interface TabSetProps {
  id: string;
  type?: "tabs" | "pills";
  className?: string | string[];
  tabPanelsClassName?: string | string[];
  tabControlsClassName?: string | string;
  tools?: ReactNode;
  children:
    | ReactElement<TabPanelProps>
    | (ReactElement<TabPanelProps> | null | undefined)[];
}

interface TabPanelProps {
  id: string;
  index?: number;
  selected?: boolean;
  style?: CSSProperties;
  scrollable?: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  className?: string | string[];
  children?: ReactNode;
  title: string;
  icon?: string;
  onSelected: (e: MouseEvent<HTMLElement>) => void;
}

export const TabSet: FC<TabSetProps> = ({
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
const Tab: FC<{
  type?: "tabs" | "pills";
  tab: ReactElement<TabPanelProps>;
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
        onClick={tab.props.onSelected}
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
const TabPanels: FC<{
  id: string;
  tabs: ReactElement<TabPanelProps>[];
  className?: string | string[];
}> = ({ id, tabs, className }) => (
  <div className={clsx("tab-content", className)} id={`${id}-content`}>
    {tabs.map((tab, index) => (
      <TabPanel key={tab.props.id} {...tab.props} index={index} />
    ))}
  </div>
);

// Individual Tab Panel
export const TabPanel: FC<TabPanelProps> = ({
  id,
  selected,
  style,
  scrollable = true,
  scrollRef,
  className,
  children,
}) => {
  const tabContentsId = computeTabContentsId(id);
  const panelRef = useRef<HTMLDivElement>(null);
  const tabContentsRef = scrollRef || panelRef;

  // Attach a scroll listener to this ref to track scrolling
  useStatefulScrollPosition(tabContentsRef, tabContentsId, 1000, scrollable);

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
    >
      {children}
    </div>
  );
};

// Tab Tools Component
const TabTools: FC<{ tools?: ReactNode }> = ({ tools }) => (
  <div className={clsx("tab-tools", moduleStyles.tabTools)}>{tools}</div>
);

// Utility functions
const computeTabId = (id: string, index: number) => `${id}-${index}`;
const computeTabContentsId = (id: string) => `${id}-contents`;

const flattenChildren = (
  children: ReactNode,
): ReactElement<TabPanelProps>[] => {
  return Children.toArray(children).flatMap((child) => {
    if (isValidElement(child)) {
      const element = child as ReactElement<any>;

      if (element.type === Fragment) {
        return flattenChildren(element.props.children);
      }
      return element;
    }
    return [];
  });
};
