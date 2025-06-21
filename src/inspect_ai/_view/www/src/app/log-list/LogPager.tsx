import clsx from "clsx";
import { FC } from "react";

import { usePagination } from "../../state/hooks";
import { ApplicationIcons } from "../appearance/icons";
import styles from "./LogPager.module.css";
import { kDefaultPageSize, kLogsPaginationId } from "./LogsPanel";

interface LogPagerProps {
  itemCount: number;
}

export const LogPager: FC<LogPagerProps> = ({ itemCount }) => {
  const { page, itemsPerPage, setPage } = usePagination(
    kLogsPaginationId,
    kDefaultPageSize,
  );
  const pageCount = Math.ceil(itemCount / itemsPerPage);
  if (pageCount <= 1) {
    return null;
  }

  const currentPage = page || 0;

  const generatePaginationSegments = () => {
    const segments: Array<{
      type: "page" | "ellipsis";
      page?: number;
      key: string;
    }> = [];

    if (pageCount <= 5) {
      // Show all pages if 5 or fewer
      for (let i = 0; i < pageCount; i++) {
        segments.push({ type: "page", page: i, key: `page-${i}` });
      }
    } else {
      // There are more than 5 pages, use ellpsis to constrain the size

      // first page
      segments.push({ type: "page", page: 0, key: "page-0" });

      // Determine the range around current page
      const startPage = Math.max(1, currentPage - 1);
      const endPage = Math.min(pageCount - 2, currentPage + 1);

      // Add ellipsis before middle section if needed
      if (startPage > 1) {
        segments.push({ type: "ellipsis", key: "ellipsis-start" });
      }

      // Add middle section pages
      for (let i = startPage; i <= endPage; i++) {
        segments.push({ type: "page", page: i, key: `page-${i}` });
      }

      // Add ellipsis after middle section if needed
      if (endPage < pageCount - 2) {
        segments.push({ type: "ellipsis", key: "ellipsis-end" });
      }

      // last page
      segments.push({
        type: "page",
        page: pageCount - 1,
        key: `page-${pageCount - 1}`,
      });
    }

    return segments;
  };

  const segments = generatePaginationSegments();

  return (
    <nav aria-label="Log Pagination">
      <ul className={clsx("pagination", styles.pager)}>
        <li className={clsx(currentPage === 0 ? "disabled" : "", styles.item)}>
          <a
            className={clsx("page-link")}
            onClick={() => {
              if (currentPage > 0) {
                setPage(currentPage - 1);
              }
            }}
          >
            <i className={clsx(ApplicationIcons.navbar.back)} />
          </a>
        </li>

        {segments.map((segment) => (
          <li
            key={segment.key}
            className={clsx(
              segment.type === "page" && segment.page === currentPage
                ? "active"
                : undefined,
              segment.type === "ellipsis" ? "disabled" : undefined,
              styles.item,
            )}
          >
            <a
              className={clsx("page-link")}
              onClick={() => {
                if (segment.type === "page" && segment.page !== undefined) {
                  setPage(segment.page);
                }
              }}
            >
              {segment.type === "page" ? segment.page! + 1 : "..."}
            </a>
          </li>
        ))}
        <li
          className={clsx(
            currentPage + 1 >= pageCount ? "disabled" : "",
            styles.item,
          )}
        >
          <a
            className={clsx("page-link")}
            onClick={() => {
              if (currentPage < pageCount) {
                setPage(currentPage + 1);
              }
            }}
          >
            <i className={clsx(ApplicationIcons.navbar.forward)} />
          </a>
        </li>
      </ul>
    </nav>
  );
};
