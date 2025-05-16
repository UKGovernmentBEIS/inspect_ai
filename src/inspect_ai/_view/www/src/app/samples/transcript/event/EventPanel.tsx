import clsx from "clsx";
import {
  FC,
  isValidElement,
  ReactElement,
  ReactNode,
  useCallback,
  useState,
} from "react";
import { ApplicationIcons } from "../../../appearance/icons";
import { EventNavs } from "./EventNavs";

import { useParams } from "react-router-dom";
import { CopyButton } from "../../../../components/CopyButton";
import { useCollapseSampleEvent, useProperty } from "../../../../state/hooks";
import {
  sampleEventUrl,
  supportsLinking,
  toFullUrl,
} from "../../../routing/url";
import { kTranscriptCollapseScope } from "../types";
import styles from "./EventPanel.module.css";

interface EventPanelProps {
  id: string;
  depth: number;
  className?: string | string[];
  title?: string;
  subTitle?: string;
  text?: string;
  icon?: string;
  children?: ReactNode | ReactNode[];
  childIds?: string[];
  collapsibleContent?: boolean;
  collapseControl?: "top" | "bottom";
}

interface ChildProps {
  "data-name"?: string;
}

/**
 * Renders the StateEventView component.
 */
export const EventPanel: FC<EventPanelProps> = ({
  id,
  depth,
  className,
  title,
  subTitle,
  text,
  icon,
  children,
  childIds,
  collapsibleContent,
  collapseControl = "top",
}) => {
  const [collapsed, setCollapsed] = useCollapseSampleEvent(
    kTranscriptCollapseScope,
    id,
  );
  const isCollapsible = (childIds || []).length > 0 || collapsibleContent;
  const useBottomDongle = isCollapsible && collapseControl === "bottom";

  // Get all URL parameters at component level
  const { logPath, sampleId, epoch } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const url =
    logPath && supportsLinking()
      ? toFullUrl(sampleEventUrl(id, logPath, sampleId, epoch))
      : undefined;

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
  if (isCollapsible && !useBottomDongle) {
    gridColumns.push("minmax(0, max-content)");
  }

  // icon
  if (icon) {
    gridColumns.push("max-content");
  }

  // title
  gridColumns.push("minmax(0, max-content)");
  // id
  if (url) {
    gridColumns.push("minmax(0, max-content)");
  }
  gridColumns.push("auto");
  gridColumns.push("minmax(0, max-content)");
  gridColumns.push("minmax(0, max-content)");

  const toggleCollapse = useCallback(() => {
    setCollapsed(!collapsed);
  }, [setCollapsed, collapsed, childIds]);

  const [mouseOver, setMouseOver] = useState(false);

  const titleEl =
    title || icon || filteredArrChildren.length > 1 ? (
      <div
        title={subTitle}
        className={clsx("text-size-small", mouseOver ? styles.hover : "")}
        style={{
          display: "grid",
          gridTemplateColumns: gridColumns.join(" "),
          columnGap: "0.3em",
          cursor: isCollapsible && !useBottomDongle ? "pointer" : undefined,
        }}
        onMouseEnter={() => setMouseOver(true)}
        onMouseLeave={() => setMouseOver(false)}
      >
        {isCollapsible && !useBottomDongle ? (
          <i
            onClick={toggleCollapse}
            className={
              collapsed
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
        {url ? (
          <CopyButton
            value={url}
            icon={ApplicationIcons.link}
            className={clsx(styles.copyLink)}
          />
        ) : (
          ""
        )}
        <div onClick={toggleCollapse}></div>
        <div
          className={clsx("text-style-secondary", styles.label)}
          onClick={toggleCollapse}
        >
          {collapsed ? text : ""}
        </div>
        <div className={styles.navs}>
          {isCollapsible && collapsibleContent && collapsed ? (
            ""
          ) : filteredArrChildren && filteredArrChildren.length > 1 ? (
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
    <div
      id={id}
      className={clsx(
        className,
        styles.card,
        depth === 0 ? styles.root : undefined,
      )}
    >
      {titleEl}
      <div
        className={clsx(
          "tab-content",
          styles.cardContent,
          isCollapsible && collapsed && collapsibleContent
            ? styles.hidden
            : undefined,
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

      {isCollapsible && useBottomDongle ? (
        <div
          className={clsx(styles.bottomDongle, "text-size-smallest")}
          onClick={toggleCollapse}
        >
          <i
            className={clsx(
              collapsed
                ? ApplicationIcons.chevron.right
                : ApplicationIcons.chevron.down,
              styles.dongleIcon,
            )}
          />
          transcript ({childIds?.length}{" "}
          {childIds?.length === 1 ? "event" : "events"})
        </div>
      ) : undefined}
    </div>
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
