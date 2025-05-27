import clsx from "clsx";
import { FC } from "react";
import { useStore } from "../../state/store";

import styles from "./LogPager.module.css";

interface LogPagerProps {
  itemCount: number;
}

export const LogPager: FC<LogPagerProps> = ({ itemCount }) => {
  const page = useStore((state) => state.logs.page);
  const itemsPerPage = useStore((state) => state.logs.itemsPerPage);
  const pageCount = Math.ceil(itemCount / itemsPerPage);

  const setPage = useStore((state) => state.logsActions.setPage);

  const currentPage = page || 0;

  return (
    <nav aria-label="Log Pagination">
      <ul className={clsx("pagination", styles.pager)}>
        <li className={clsx("page-item", currentPage === 0 ? "disabled" : "", styles.item) }>
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
              styles.item
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
            styles.item
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
