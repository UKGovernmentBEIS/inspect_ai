import clsx from "clsx";
import { FC, ReactNode, useRef } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../../state/store";
import { basename, dirname, ensureTrailingSlash } from "../../utils/path";
import { ApplicationIcons } from "../appearance/icons";
import { logUrl, useLogRouteParams } from "../routing/url";
import styles from "./Navbar.module.css";

interface NavbarProps {
  children?: ReactNode;
}

export const Navbar: FC<NavbarProps> = ({ children }) => {
  const { logPath } = useLogRouteParams();
  const logs = useStore((state) => state.logs.logs);
  const baseLogDir = dirname(logs.log_dir || "");
  const baseLogName = basename(logs.log_dir || "");
  const pathSegments = logPath ? logPath.split("/") : undefined;

  const navRef = useRef<HTMLElement>(null);
  const breadcrumbRef = useRef<HTMLOListElement>(null);

  const backUrl = logUrl(
    ensureTrailingSlash(dirname(logPath || "")),
    logs.log_dir,
  );

  const dirSegments: Array<{ text: string; url: string }> = [];
  const currentSegment = [];
  for (const pathSegment of pathSegments || []) {
    currentSegment.push(pathSegment);
    const segmentUrl = logUrl(currentSegment.join("/"), logs.log_dir);
    dirSegments.push({
      text: pathSegment,
      url: segmentUrl,
    });
  }

  const segments: Array<{ text: string; url?: string }> = [
    { text: prettyDirUri(baseLogDir) },
    { text: baseLogName, url: logUrl("", logs.log_dir) },
    ...dirSegments,
  ];

  return (
    <nav
      ref={navRef}
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
        <div className={clsx(styles.pathContainer)}>
          <ol
            className={clsx("breadcrumb", styles.breadcrumbs)}
            ref={breadcrumbRef}
          >
            {segments?.map((segment, index) => {
              // Show all segments when not collapsed
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
                    <span className={clsx(styles.pathSegment)}>
                      {segment.text}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        </div>
      </div>
      <div className={clsx(styles.right)}>{children}</div>
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
