import clsx from "clsx";
import { FC, ReactNode, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { PopOver } from "../../../../components/PopOver";
import { PulsingDots } from "../../../../components/PulsingDots";
import {
  useCollapseSampleEvent,
  useSamplePopover,
} from "../../../../state/hooks";
import { formatDateTime, formatTime } from "../../../../utils/format";
import { parsePackageName } from "../../../../utils/python";
import { ApplicationIcons } from "../../../appearance/icons";
import { MetaDataGrid } from "../../../content/MetaDataGrid";
import { sampleEventUrl } from "../../../routing/url";
import { kSandboxSignalName } from "../transform/fixups";
import { EventNode } from "../types";
import styles from "./OutlineRow.module.css";

export interface OutlineRowProps {
  node: EventNode;
  collapseScope: string;
  running?: boolean;
}

export const OutlineRow: FC<OutlineRowProps> = ({
  node,
  collapseScope,
  running,
}) => {
  const [collapsed, setCollapsed] = useCollapseSampleEvent(
    collapseScope,
    node.id,
  );
  const icon = iconForNode(node);
  const toggle = toggleIcon(node, collapsed);

  const popoverId = `${node.id}-popover`;
  const { show, hide, isShowing } = useSamplePopover(popoverId);

  const ref = useRef(null);

  // Get all URL parameters at component level
  const { logPath, sampleId, epoch } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();

  const url = logPath
    ? sampleEventUrl(node.id, logPath, sampleId, epoch)
    : undefined;

  return (
    <>
      <div
        className={clsx(styles.eventRow, "text-size-smallest")}
        style={{ paddingLeft: `${node.depth * 0.4}em` }}
      >
        <div
          className={clsx(styles.toggle)}
          onClick={() => {
            setCollapsed(!collapsed);
          }}
        >
          {toggle ? <i className={clsx(toggle)} /> : undefined}
        </div>
        <div className={clsx(styles.label)} data-depth={node.depth}>
          {icon ? <i className={clsx(icon, styles.icon)} /> : undefined}
          {url ? (
            <Link
              to={url}
              className={clsx(styles.eventLink)}
              ref={ref}
              onMouseOver={show}
              onMouseLeave={hide}
            >
              {parsePackageName(labelForNode(node)).module}
            </Link>
          ) : (
            <span ref={ref} onMouseOver={show} onMouseLeave={hide}>
              {parsePackageName(labelForNode(node)).module}
            </span>
          )}
          {running ? (
            <PulsingDots
              size="small"
              className={clsx(styles.progress)}
              subtle={false}
            />
          ) : undefined}
        </div>
      </div>
      <PopOver
        id={`${node.id}-popover`}
        positionEl={ref.current}
        isOpen={isShowing}
        className={clsx(styles.popper)}
        placement="auto-end"
      >
        {summarizeNode(node)}
      </PopOver>
    </>
  );
};

const toggleIcon = (
  node: EventNode,
  collapsed: boolean,
): string | undefined => {
  if (node.children.length > 0) {
    return collapsed
      ? ApplicationIcons.chevron.right
      : ApplicationIcons.chevron.down;
  }
};

const iconForNode = (node: EventNode): string | undefined => {
  switch (node.event.event) {
    case "sample_limit":
      return ApplicationIcons.limits.custom;

    case "score":
      return ApplicationIcons.scorer;

    case "error":
      return ApplicationIcons.error;
  }
};

const labelForNode = (node: EventNode): string => {
  if (node.event.event === "span_begin") {
    switch (node.event.type) {
      case "solver":
        return node.event.name;
      case "tool":
        return node.event.name;
      default: {
        if (node.event.name === kSandboxSignalName) {
          return "sandbox events";
        }
        return node.event.name;
      }
    }
  } else {
    switch (node.event.event) {
      case "subtask":
        return node.event.name;
      case "approval":
        switch (node.event.decision) {
          case "approve":
            return "approved";
          case "reject":
            return "rejected";
          case "escalate":
            return "escalated";
          case "modify":
            return "modified";
          case "terminate":
            return "terminated";
          default:
            return node.event.decision;
        }
      case "model":
        return `model${node.event.role ? ` (${node.event.role})` : ""}`;
      case "score":
        return "scoring";
      case "step":
        if (node.event.name === kSandboxSignalName) {
          return "sandbox events";
        }
        return node.event.name;

      default:
        return node.event.event;
    }
  }
};

export const summarizeNode = (node: EventNode): ReactNode => {
  let entries: Record<string, unknown> = {};
  switch (node.event.event) {
    case "sample_init":
      entries = {
        started: formatDateTime(new Date(node.event.timestamp)),
        sample_id: node.event.sample.id,
        sandbox: node.event.sample.sandbox?.type,
        working_start: formatTime(node.event.working_start),
      };
      break;

    case "sample_limit":
      entries = {
        started: formatDateTime(new Date(node.event.timestamp)),
        type: node.event.type,

        message: node.event.message,
        limit: node.event.limit,
        working_start: formatTime(node.event.working_start),
      };
      break;
    case "score":
      entries = {
        started: formatDateTime(new Date(node.event.timestamp)),
        answer: node.event.score.answer,
        score: node.event.score.value,
        working_start: formatTime(node.event.working_start),
      };
      break;
    default:
      entries = {
        started: formatDateTime(new Date(node.event.timestamp)),
        event: node.event.event,
        working_start: formatTime(node.event.working_start),
      };
  }

  return (
    <MetaDataGrid
      entries={entries}
      size="mini"
      className={clsx(styles.popover, "text-size-smallest")}
    />
  );
};
