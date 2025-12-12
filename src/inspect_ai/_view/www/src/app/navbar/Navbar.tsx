import clsx from "clsx";
import { FC, Fragment, ReactNode, useMemo, useRef } from "react";
import { Link } from "react-router-dom";
import { usePagination } from "../../state/hooks";
import { useStore } from "../../state/store";
import { basename, dirname, ensureTrailingSlash } from "../../utils/path";
import { prettyDirUri } from "../../utils/uri";
import { ApplicationIcons } from "../appearance/icons";
import { kDefaultPageSize, kLogsPaginationId } from "../log-list/LogsPanel";
import styles from "./Navbar.module.css";
import { useBreadcrumbTruncation } from "./useBreadcrumbTruncation";

interface NavbarProps {
  children?: ReactNode;
  bordered?: boolean;
  fnNavigationUrl: (file: string, log_dir?: string) => string;
  currentPath: string | undefined;
}

export const Navbar: FC<NavbarProps> = ({
  fnNavigationUrl,
  bordered,
  children,
  currentPath,
}) => {
  const logDir = useStore((state) => state.logs.logDir);
  const baseLogDir = dirname(logDir || "");
  const baseLogName = basename(logDir || "");
  const pathContainerRef = useRef<HTMLDivElement>(null);
  const { setPage } = usePagination(kLogsPaginationId, kDefaultPageSize);

  const backUrl = fnNavigationUrl(
    ensureTrailingSlash(dirname(currentPath || "")),
    logDir,
  );

  const segments = useMemo(() => {
    const pathSegments = currentPath ? currentPath.split("/") : [];
    const dirSegments: Array<{ text: string; url: string }> = [];
    const currentSegment = [];
    for (const pathSegment of pathSegments) {
      currentSegment.push(pathSegment);
      const segmentUrl = fnNavigationUrl(currentSegment.join("/"), logDir);
      dirSegments.push({
        text: pathSegment,
        url: segmentUrl,
      });
    }

    return [
      { text: prettyDirUri(baseLogDir) },
      { text: baseLogName, url: fnNavigationUrl("", logDir) },
      ...dirSegments,
    ];
  }, [baseLogDir, baseLogName, currentPath, fnNavigationUrl, logDir]);

  const { visibleSegments, showEllipsis } = useBreadcrumbTruncation(
    segments,
    pathContainerRef,
  );

  return (
    <nav
      className={clsx(
        "text-size-smaller",
        "header-nav",
        styles.header,
        bordered === false ? null : styles.bordered,
      )}
      aria-label="breadcrumb"
      data-unsearchable={true}
    >
      <div className={clsx(styles.left)}>
        <Link to={backUrl} className={clsx(styles.toolbarButton)}>
          <i className={clsx(ApplicationIcons.navbar.back)} />
        </Link>
        <Link
          to={fnNavigationUrl("", logDir)}
          className={clsx(styles.toolbarButton)}
          onClick={() => {
            setPage(0);
          }}
        >
          <i className={clsx(ApplicationIcons.navbar.home)} />
        </Link>
        <div className={clsx(styles.pathContainer)} ref={pathContainerRef}>
          {logDir ? (
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
                      {segment.url && !isLast ? (
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
