interface NavbarProps {}

import clsx from "clsx";
import { FC } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../../state/store";
import { basename, dirname, ensureTrailingSlash } from "../../utils/path";
import { ApplicationIcons } from "../appearance/icons";
import { logUrl, useLogRouteParams } from "../routing/url";
import styles from "./Navbar.module.css";

export const Navbar: FC<NavbarProps> = () => {
  const { logPath } = useLogRouteParams();
  const logs = useStore((state) => state.logs.logs);
  const baseLogDir = dirname(logs.log_dir || "");
  const baseLogName = basename(logs.log_dir || "");
  const pathSegments = logPath ? logPath.split("/") : undefined;

  const backUrl = logUrl(
    ensureTrailingSlash(dirname(logPath || "")),
    logs.log_dir,
  );

  const dirSegments = pathSegments
    ? pathSegments.map((segment) => {
        return {
          text: segment,
          url: logUrl(segment, logs.log_dir),
        };
      })
    : [];

  const segments: Array<{ text: string; url?: string }> = [
    { text: prettyDirUri(baseLogDir) },
    { text: baseLogName, url: logUrl("", logs.log_dir) },
    ...dirSegments,
  ];

  return (
    <nav
      className={clsx("text-size-smaller", styles.header)}
      aria-label="breadcrumb"
    >
      <div className={clsx(styles.left)}>
        <Link to={backUrl} className={clsx(styles.toolbarButton)}>
          <i className={clsx(ApplicationIcons.navbar.back)} />
        </Link>
        <Link
          to={logUrl("", logs.log_dir)}
          className={clsx(styles.toolbarButton)}
        >
          <i className={clsx(ApplicationIcons.navbar.home)} />
        </Link>

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
      </div>
    </nav>
  );
};

const prettyDirUri = (uri: string) => {
  if (uri.startsWith("file://")) {
    return uri.replace("file://", "");
  } else {
    return uri;
  }
};
