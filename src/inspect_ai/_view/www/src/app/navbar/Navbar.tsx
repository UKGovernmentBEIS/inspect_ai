import clsx from "clsx";
import { FC, Fragment, ReactNode, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import { useStore } from "../../state/store";
import { basename, dirname, ensureTrailingSlash } from "../../utils/path";
import { ApplicationIcons } from "../appearance/icons";
import { logUrl, useLogRouteParams } from "../routing/url";
import styles from "./Navbar.module.css";
import { useBreadcrumbTruncation } from "./useBreadcrumbTruncation";

interface NavbarProps {
  children?: ReactNode;
}

export const Navbar: FC<NavbarProps> = ({ children }) => {
  const { logPath } = useLogRouteParams();
  const logs = useStore((state) => state.logs.logs);
  const baseLogDir = dirname(logs.log_dir || "");
  const baseLogName = basename(logs.log_dir || "");
  const pathContainerRef = useRef<HTMLDivElement>(null);

  const backUrl = logUrl(
    ensureTrailingSlash(dirname(logPath || "")),
    logs.log_dir,
  );

  const segments = useMemo(() => {
    const pathSegments = logPath ? logPath.split("/") : [];
    const dirSegments: Array<{ text: string; url: string }> = [];
    const currentSegment = [];
    for (const pathSegment of pathSegments) {
      currentSegment.push(pathSegment);
      const segmentUrl = logUrl(currentSegment.join("/"), logs.log_dir);
      dirSegments.push({
        text: pathSegment,
        url: segmentUrl,
      });
    }

    return [
      { text: prettyDirUri(baseLogDir) },
      { text: baseLogName, url: logUrl("", logs.log_dir) },
      ...dirSegments,
    ];
  }, [baseLogDir, baseLogName, logPath, logs.log_dir]);

  const { visibleSegments, showEllipsis } = useBreadcrumbTruncation(
    segments,
    pathContainerRef,
  );

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
        <div className={clsx(styles.pathContainer)} ref={pathContainerRef}>
          {logs.log_dir ? (
            <ol className={clsx("breadcrumb", styles.breadcrumbs)}>
              {visibleSegments?.map((segment, index) => {
                const isLast = index === visibleSegments.length - 1;
                const shouldShowEllipsis =
                  showEllipsis && index === 1 && visibleSegments.length >= 2;

                return (
                  <Fragment key={index}>
                    {shouldShowEllipsis && (
                      <li className={clsx("breadcrumb-item", styles.ellipsis)}>
                        <span>...</span>
                      </li>
                    )}
                    <li
                      className={clsx(
                        styles.pathLink,
                        "breadcrumb-item",
                        isLast ? "active" : undefined,
                      )}
                    >
                      {segment.url ? (
                        <Link to={segment.url}>{segment.text}</Link>
                      ) : (
                        <span className={clsx(styles.pathSegment)}>
                          {segment.text}
                        </span>
                      )}
                    </li>
                  </Fragment>
                );
              })}
            </ol>
          ) : (
            ""
          )}
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
