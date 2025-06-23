import clsx from "clsx";
import { FC, Fragment, PropsWithChildren, ReactElement } from "react";
import { Citation } from "./types";

import { decodeHtmlEntities } from "../../../utils/html";
import styles from "./MessageCitations.module.css";
import { UrlCitation as UrlCitationType } from "../../../@types/log";

export interface MessageCitationsProps {
  citations: Citation[];
}

export const MessageCitations: FC<MessageCitationsProps> = ({ citations }) => {
  if (citations.length === 0) {
    return undefined;
  }

  return (
    <div className={clsx(styles.citations, "text-size-smallest")}>
      {citations.map((citation, index) => (
        <Fragment key={index}>
          <span>{index + 1}</span>
          <MessageCitation citation={citation} />
        </Fragment>
      ))}
    </div>
  );
};

interface MessageCitationProps {
  citation: Citation;
}

const MessageCitation: FC<MessageCitationProps> = ({ citation }) => {
  const innards = decodeHtmlEntities(
    citation.title ??
      (typeof citation.cited_text === "string" ? citation.cited_text : ""),
  );
  return citation.type === "url" ? (
    <UrlCitation citation={citation}>{innards}</UrlCitation>
  ) : (
    <OtherCitation>{innards}</OtherCitation>
  );
};

const UrlCitation: FC<PropsWithChildren<{ citation: UrlCitationType }>> = ({
  children,
  citation,
}): ReactElement => (
  <a
    href={citation.url}
    target="_blank"
    rel="noopener noreferrer"
    className={clsx(styles.citationLink)}
    title={`${citation.cited_text || ""}\n${citation.url}`}
  >
    {children}
  </a>
);

const OtherCitation: FC<PropsWithChildren> = ({ children }): ReactElement => (
  <>{children}</>
);
