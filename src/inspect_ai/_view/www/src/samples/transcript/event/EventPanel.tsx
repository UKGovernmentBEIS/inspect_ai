import clsx from "clsx";
import { FC, isValidElement, ReactNode, useCallback } from "react";
import { ApplicationIcons } from "../../../appearance/icons";
import { EventNavs } from "./EventNavs";

import { useStore } from "../../../state/store";
import styles from "./EventPanel.module.css";

interface EventPanelProps {
  id: string;
  className?: string | string[];
  title?: string;
  subTitle?: string;
  text?: string;
  icon?: string;
  collapse?: boolean;
  children?: ReactNode | ReactNode[];
}

interface ChildProps {
  "data-name"?: string;
}

const kCollapsed = "collapsed";
const kSelectedNav = "selectedNav";

/**
 * Renders the StateEventView component.
 */
export const EventPanel: FC<EventPanelProps> = ({
  id,
  className,
  title,
  subTitle,
  text,
  icon,
  collapse,
  children,
}) => {
  const setPropertyValue = useStore(
    (state) => state.appActions.setPropertyValue,
  );
  const isCollapsed = useStore((state) =>
    state.appActions.getPropertyValue<boolean>(id, kCollapsed, !!collapse),
  );
  const setCollapsed = useCallback(
    (collapsed: boolean) => {
      setPropertyValue(id, kCollapsed, collapsed);
    },
    [setPropertyValue],
  );
  const hasCollapse = collapse !== undefined;

  const pillId = (index: number) => {
    return `${id}-nav-pill-${index}`;
  };
  const filteredArrChildren = (
    Array.isArray(children) ? children : [children]
  ).filter((child) => !!child);
  const defaultPillId = pillId(0);

  const selectedNav = useStore((state) =>
    state.appActions.getPropertyValue<string>(id, kSelectedNav, defaultPillId),
  );
  const setSelectedNav = useCallback(
    (nav: string) => {
      setPropertyValue(id, kSelectedNav, nav);
    },
    [setPropertyValue],
  );

  const gridColumns = [];

  // chevron
  if (hasCollapse) {
    gridColumns.push("minmax(0, max-content)");
  }

  // icon
  if (icon) {
    gridColumns.push("max-content");
  }

  // title
  gridColumns.push("minmax(0, max-content)");
  gridColumns.push("auto");
  gridColumns.push("minmax(0, max-content)");
  gridColumns.push("minmax(0, max-content)");

  const titleEl =
    title || icon || filteredArrChildren.length > 1 ? (
      <div
        title={subTitle}
        className={clsx("text-size-small")}
        style={{
          display: "grid",
          gridTemplateColumns: gridColumns.join(" "),
          columnGap: "0.3em",
          cursor: hasCollapse ? "pointer" : undefined,
        }}
      >
        {hasCollapse ? (
          <i
            onClick={() => {
              setCollapsed(!isCollapsed);
            }}
            className={
              isCollapsed
                ? ApplicationIcons.chevron.right
                : ApplicationIcons.chevron.down
            }
          />
        ) : (
          ""
        )}
        {icon ? (
          <i
            className={clsx(
              icon || ApplicationIcons.metadata,
              "text-style-secondary",
            )}
            onClick={() => {
              setCollapsed(!isCollapsed);
            }}
          />
        ) : (
          ""
        )}
        <div
          className={clsx("text-style-secondary", "text-style-label")}
          onClick={() => {
            setCollapsed(!isCollapsed);
          }}
        >
          {title}
        </div>
        <div
          onClick={() => {
            setCollapsed(!isCollapsed);
          }}
        ></div>
        <div
          className={clsx("text-style-secondary", styles.label)}
          onClick={() => {
            setCollapsed(!isCollapsed);
          }}
        >
          {isCollapsed ? text : ""}
        </div>
        <div className={styles.navs}>
          {(!hasCollapse || !isCollapsed) &&
          filteredArrChildren &&
          filteredArrChildren.length > 1 ? (
            <EventNavs
              navs={filteredArrChildren.map((child, index) => {
                const defaultTitle = `Tab ${index}`;
                const title =
                  child && isValidElement<ChildProps>(child)
                    ? (child.props as ChildProps)["data-name"] || defaultTitle
                    : defaultTitle;
                return {
                  id: `eventpanel-${id}-${index}`,
                  title: title,
                  target: pillId(index),
                };
              })}
              selectedNav={selectedNav}
              setSelectedNav={setSelectedNav}
            />
          ) : (
            ""
          )}
        </div>
      </div>
    ) : (
      ""
    );

  const card = (
    <div id={id} className={clsx(className, styles.card)}>
      {titleEl}
      <div
        className={clsx(
          "tab-content",
          styles.cardContent,
          hasCollapse && isCollapsed ? styles.hidden : undefined,
        )}
      >
        {filteredArrChildren?.map((child, index) => {
          const id = pillId(index);
          const isSelected = id === selectedNav;

          return (
            <div
              key={`children-${id}-${index}`}
              id={id}
              className={clsx("tab-pane", "show", isSelected ? "active" : "")}
            >
              {child}
            </div>
          );
        })}
      </div>
    </div>
  );
  return card;
};
