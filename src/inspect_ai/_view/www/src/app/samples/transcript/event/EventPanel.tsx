import clsx from "clsx";
import {
  FC,
  isValidElement,
  ReactElement,
  ReactNode,
  useCallback,
} from "react";
import { ApplicationIcons } from "../../../appearance/icons";
import { EventNavs } from "./EventNavs";

import { useProperty } from "../../../../state/hooks";
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
  running?: boolean;
}

interface ChildProps {
  "data-name"?: string;
}

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
  const [isCollapsed, setCollapsed] = useProperty(id, "collapsed", {
    defaultValue: !!collapse,
  });

  const hasCollapse = collapse !== undefined;

  const pillId = (index: number) => {
    return `${id}-nav-pill-${index}`;
  };
  const filteredArrChildren = (
    Array.isArray(children) ? children : [children]
  ).filter((child) => !!child);

  const defaultPill = filteredArrChildren.findIndex((node) => {
    return hasDataDefault(node) && node.props["data-default"];
  });
  const defaultPillId = defaultPill !== -1 ? pillId(defaultPill) : pillId(0);

  const [selectedNav, setSelectedNav] = useProperty(id, "selectedNav", {
    defaultValue: defaultPillId,
  });

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

  const toggleCollapse = useCallback(() => {
    setCollapsed(!isCollapsed);
  }, [setCollapsed, isCollapsed]);

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
            onClick={toggleCollapse}
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
            onClick={toggleCollapse}
          />
        ) : (
          ""
        )}
        <div
          className={clsx("text-style-secondary", "text-style-label")}
          onClick={toggleCollapse}
        >
          {title}
        </div>
        <div onClick={toggleCollapse}></div>
        <div
          className={clsx("text-style-secondary", styles.label)}
          onClick={toggleCollapse}
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
    <>
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
    </>
  );
  return card;
};

// Typeguard for reading default value from pills
interface DataDefaultProps {
  "data-default"?: boolean;
  [key: string]: any;
}

function hasDataDefault(
  node: ReactNode,
): node is ReactElement<DataDefaultProps> {
  return (
    isValidElement(node) &&
    node.props !== null &&
    typeof node.props === "object" &&
    "data-default" in node.props
  );
}
