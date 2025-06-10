import clsx from "clsx";
import { FC, ReactNode, useEffect, useRef, useState } from "react";
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
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [collapsedCount, setCollapsedCount] = useState(0);

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

  useEffect(() => {
    const navElement = navRef.current;
    const breadcrumbElement = breadcrumbRef.current;
    if (!navElement || !breadcrumbElement) {
      return;
    }

    const checkOverflow = () => {
      const navWidth = navElement.clientWidth;
      const breadcrumbRect = breadcrumbElement.getBoundingClientRect();
      const navRect = navElement.getBoundingClientRect();

      // Calculate how much space is available for breadcrumbs
      const breadcrumbLeftPosition = breadcrumbRect.left - navRect.left;
      const availableWidth = navWidth - breadcrumbLeftPosition - 16; // 16px padding buffer
      const breadcrumbWidth = breadcrumbElement.scrollWidth;

      // Only collapse if we have more than 3 segments and there's overflow
      if (
        breadcrumbWidth > availableWidth &&
        segments.length > 3 &&
        !isCollapsed
      ) {
        // Start with collapsing 1 segment and increase if needed
        let toCollapse = 1;
        if (segments.length > 5) {
          toCollapse = Math.min(
            segments.length - 3,
            Math.ceil((segments.length - 2) / 2),
          );
        }
        setCollapsedCount(toCollapse);
        setIsCollapsed(true);
      } else if (isCollapsed) {
        // Check if we can auto-expand when window gets larger
        const estimatedFullWidth =
          breadcrumbWidth *
          (segments.length / (segments.length - collapsedCount + 1));
        if (estimatedFullWidth < availableWidth * 0.8) {
          setIsCollapsed(false);
          setCollapsedCount(0);
        }
      }
    };

    // Check on mount and when segments change
    requestAnimationFrame(checkOverflow);

    const resizeObserver = new ResizeObserver(checkOverflow);
    resizeObserver.observe(navElement);

    return () => resizeObserver.disconnect();
  }, [segments.length, isCollapsed]);

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

        <ol
          className={clsx("breadcrumb", styles.breadcrumbs)}
          ref={breadcrumbRef}
        >
          {segments?.map((segment, index) => {
            if (!isCollapsed) {
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
            }

            // When collapsed, show first segment, ellipsis, and last segments
            const isLastSegment = index === segments.length - 1;
            const isInMiddleRange = index > 0 && index < segments.length - 1;
            const shouldShowEllipsis = index === 1 && collapsedCount > 0;

            // Hide middle segments except for the ellipsis position
            if (isInMiddleRange && !shouldShowEllipsis) {
              return null;
            }

            return (
              <li
                className={clsx(
                  styles.pathLink,
                  "breadcrumb-item",
                  isLastSegment ? "active" : undefined,
                )}
                key={index}
              >
                {shouldShowEllipsis ? (
                  <span className={clsx(styles.pathSegment)}>...</span>
                ) : segment.url ? (
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
