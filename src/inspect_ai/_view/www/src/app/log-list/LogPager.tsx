import clsx from "clsx";
import { FC } from "react";

import { usePagination } from "../../state/hooks";
import styles from "./LogPager.module.css";

interface LogPagerProps {
  itemCount: number;
  logDir: string;
}

export const LogPager: FC<LogPagerProps> = ({ itemCount, logDir }) => {
  const { page, itemsPerPage, setPage } = usePagination(logDir);
  const pageCount = Math.ceil(itemCount / itemsPerPage);

  const currentPage = page || 0;

  return (
    <nav aria-label="Log Pagination">
      <ul className={clsx("pagination", styles.pager)}>
        <li
          className={clsx(
            "page-item",
            currentPage === 0 ? "disabled" : "",
            styles.item,
          )}
        >
          <a
            className={clsx("page-link")}
            onClick={() => {
              if (currentPage > 0) {
                setPage(currentPage - 1);
              }
            }}
          >
            Previous
          </a>
        </li>

        {Array.from({ length: pageCount }, (_, index) => (
          <li
            key={index}
            className={clsx(
              "page-item",
              index === currentPage ? "active" : undefined,
              styles.item,
            )}
          >
            <a
              className={clsx("page-link")}
              onClick={() => {
                setPage(index);
              }}
            >
              {index + 1}
            </a>
          </li>
        ))}
        <li
          className={clsx(
            "page-item",
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
            Next
          </a>
        </li>
      </ul>
    </nav>
  );
};
