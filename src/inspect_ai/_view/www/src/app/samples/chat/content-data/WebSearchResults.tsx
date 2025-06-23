import clsx from "clsx";
import { FC } from "react";
import styles from "./WebSearchResults.module.css";

export interface WebSearchContentData {
  title: string;
  url: string;
  page_age: string;
}

export const WebSearchResults: FC<{ results: WebSearchContentData[] }> = ({
  results,
}) => {
  return (
    <>
      <div
        className={clsx(
          styles.label,
          "text-style-label",
          "text-style-secondary",
          "text-size-smaller",
        )}
      >
        Results
      </div>

      <ol className={clsx(styles.results, "text-size-smaller")}>
        {results.map((result, index) => (
          <li
            key={index}
            className={clsx(styles.result, "text-style-secondary")}
          >
            <a
              href={result.url}
              target="_blank"
              rel="noopener noreferrer"
              title={
                result.url +
                (result.page_age ? `\n(Age: ${result.page_age})` : "")
              }
            >
              {result.title}
            </a>
          </li>
        ))}
      </ol>
    </>
  );
};
