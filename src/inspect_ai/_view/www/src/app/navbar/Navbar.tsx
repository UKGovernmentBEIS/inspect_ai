interface NavbarProps {}

import clsx from "clsx";
import { FC } from "react";
import { Link, useParams } from "react-router-dom";
import { useStore } from "../../state/store";
import { basename, dirname } from "../../utils/path";
import { logUrl } from "../routing/url";
import styles from "./Navbar.module.css";

export const Navbar: FC<NavbarProps> = () => {
  const { logPath } = useParams<{
    logPath?: string;
    tabId?: string;
    sampleId?: string;
    epoch?: string;
  }>();
  const logs = useStore((state) => state.logs.logs);
  const baseLogDir = dirname(logs.log_dir || "");
  const baseLogName = basename(logs.log_dir || "");
  const pathSegments = logPath
    ? decodeURIComponent(logPath).split("/")
    : undefined;

  const dirSegments = pathSegments
    ? pathSegments.map((segment) => {
        return {
          text: segment,
          url: logUrl(segment, logs.log_dir),
        };
      })
    : [];

  const segments: Array<{ text: string; url?: string }> = [
    { text: baseLogDir },
    { text: baseLogName, url: logUrl("", logs.log_dir) },
    ...dirSegments,
  ];

  return (
    <nav
      className={clsx("text-size-smaller", styles.header)}
      aria-label="breadcrumb"
    >
      <ol className={clsx("breadcrumb", styles.breadcrumbs)}>
        {segments?.map((segment, index) => {
          return (
            <li
              className={clsx(
                styles.pathLink,
                "breadcrumb-item",
                index === segments.length - 1 ? "active" : undefined,
              )}
              key={index}
            >
              {segment.url ? (
                <Link to={segment.url}>{segment.text}</Link>
              ) : (
                <span key={index} className={clsx(styles.pathSegment)}>
                  {segment.text}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};
