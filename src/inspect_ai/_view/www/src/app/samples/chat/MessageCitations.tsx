import clsx from "clsx";
import { FC } from "react";
import { Citation } from "./types";

import styles from "./MessageCitations.module.css";

export interface MessageCitationProps {
  citations: Citation[];
}

export const MessageCitations: FC<MessageCitationProps> = ({ citations }) => {
  if (citations.length === 0) {
    return undefined;
  }

  return (
    <div className={clsx(styles.citations, "text-size-smallest")}>
      {citations.map((citation, index) => (
        <>
          <span>{index + 1}</span>
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            title={citation.cited_text}
            className={clsx(styles.citationLink)}
          >
            {citation.cited_text}
          </a>
        </>
      ))}
    </div>
  );
};
