interface LogsHeaderProps {
  segments: Array<{
    text: string;
    url?: string;
  }>;
}

import clsx from "clsx";
import { FC } from "react";
import { Link } from "react-router-dom";
import styles from "./LogsHeader.module.css";

export const LogsHeader: FC<LogsHeaderProps> = ({ segments }) => {
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
