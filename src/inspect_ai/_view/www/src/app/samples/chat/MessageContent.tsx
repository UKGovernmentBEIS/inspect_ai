import clsx from "clsx";

import { FC, ReactNode } from "react";
import {
  ContentAudio,
  ContentData,
  ContentImage,
  ContentReasoning,
  ContentText,
  ContentVideo,
  Format1,
  Format2,
} from "../../../@types/log";
import { ContentTool } from "../../../app/types";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { ContentDataView } from "./content-data/ContentDataView";
import { MessageCitations } from "./MessageCitations";
import styles from "./MessageContent.module.css";
import { MessagesContext } from "./MessageContents";
import { ToolOutput } from "./tools/ToolOutput";
import { Citation } from "./types";

type ContentObject =
  | ContentText
  | ContentReasoning
  | ContentImage
  | ContentAudio
  | ContentVideo
  | ContentTool
  | ContentData;

type ContentType = string | string[] | ContentObject;

type Contents = string | string[] | ContentObject[];

interface MessageContentProps {
  contents: Contents;
  context: MessagesContext;
}

/**
 * Renders message content based on its type.
 * Supports rendering strings, images, and tools using specific renderers.
 */
export const MessageContent: FC<MessageContentProps> = ({
  contents,
  context,
}) => {
  const normalized = normalizeContent(contents);
  if (Array.isArray(normalized)) {
    return normalized.map((content, index) => {
      if (typeof content === "string") {
        return messageRenderers["text"].render(
          `text-content-${index}`,
          {
            type: "text",
            text: content,
            refusal: null,
            internal: null,
            citations: null,
          },
          index === contents.length - 1,
          context,
        );
      } else {
        if (content) {
          const renderer = messageRenderers[content.type];
          if (renderer) {
            return renderer.render(
              `text-${content.type}-${index}`,
              content,
              index === contents.length - 1,
              context,
            );
          } else {
            console.error(`Unknown message content type '${content.type}'`);
          }
        }
      }
    });
  } else {
    // This is a simple string
    const contentText: ContentText = {
      type: "text",
      text: normalized,
      refusal: null,
      internal: null,
      citations: null,
    };
    return messageRenderers["text"].render(
      "text-message-content",
      contentText,
      true,
      context,
    );
  }
};

interface MessageRenderer {
  render: (
    key: string,
    content: ContentType,
    isLast: boolean,
    context: MessagesContext,
  ) => ReactNode;
}

const messageRenderers: Record<string, MessageRenderer> = {
  text: {
    render: (key, content, isLast) => {
      // The context provides a way to share context between different
      // rendering. In this case, we'll use it to keep track of citations
      const c = content as ContentText;
      const cites = c.citations ?? [];

      if (!c.text && !cites.length) {
        return undefined;
      }

      return (
        <>
          <MarkdownDiv
            key={key}
            markdown={c.text || ""}
            className={isLast ? "no-last-para-padding" : ""}
          />
          {c.citations ? (
            <MessageCitations citations={c.citations as Citation[]} />
          ) : undefined}
        </>
      );
    },
  },
  reasoning: {
    render: (key, content, isLast) => {
      const r = content as ContentReasoning;
      if (!r.reasoning && !r.redacted) {
        return undefined;
      }
      return (
        <div key={key} className={clsx(styles.reasoning, "text-size-small")}>
          <div
            className={clsx(
              "text-style-label",
              "text-style-secondary",
              isLast ? "no-last-para-padding" : "",
            )}
          >
            Reasoning
          </div>
          <ExpandablePanel id={`${key}-reasoning`} collapse={true}>
            <MarkdownDiv
              markdown={
                r.redacted
                  ? "Reasoning encrypted by model provider."
                  : r.reasoning
              }
            />
          </ExpandablePanel>
        </div>
      );
    },
  },
  image: {
    render: (key, content) => {
      const c = content as ContentImage;
      if (c.image.startsWith("data:")) {
        return <img src={c.image} className={styles.contentImage} key={key} />;
      } else {
        return <code key={key}>{c.image}</code>;
      }
    },
  },
  audio: {
    render: (key, content) => {
      const c = content as ContentAudio;
      return (
        <audio controls key={key}>
          <source src={c.audio} type={mimeTypeForFormat(c.format)} />
        </audio>
      );
    },
  },
  video: {
    render: (key, content) => {
      const c = content as ContentVideo;
      return (
        <video width="500" height="375" controls key={key}>
          <source src={c.video} type={mimeTypeForFormat(c.format)} />
        </video>
      );
    },
  },
  tool: {
    render: (key, content) => {
      const c = content as ContentTool;
      return <ToolOutput output={c.content} key={key} />;
    },
  },
  data: {
    render: (key, content) => {
      const c = content as ContentData;
      return <ContentDataView id={key} contentData={c} />;
    },
  },
};

/**
 * Renders message content based on its type.
 * Supports rendering strings, images, and tools using specific renderers.
 */
const mimeTypeForFormat = (format: Format1 | Format2): string => {
  switch (format) {
    case "mov":
      return "video/quicktime";
    case "wav":
      return "audio/wav";
    case "mp3":
      return "audio/mpeg";
    case "mp4":
      return "video/mp4";
    case "mpeg":
      return "video/mpeg";
    default:
      return "video/mp4"; // Default to mp4 for unknown formats
  }
};

// This collapses sequential runs of text content into a single text content,
// adding citations as superscript counters at the end of the text for each block
// containing citations. The citations are then attached to the content where
// they can be rendered separately (with coordinating numbers).
const normalizeContent = (contents: Contents): Contents => {
  // its a string
  if (typeof contents === "string") {
    return contents;
  }

  // its an array of strings
  if (contents.length > 0 && typeof contents[0] === "string") {
    return contents;
  }

  const result: ContentObject[] = [];
  const collection: ContentText[] = [];

  const collect = () => {
    if (collection.length > 0) {
      // Flatten the citations from the collection
      const filteredCitations = collection.flatMap((c) => c.citations || []);
      // Render citations as superscript counters
      let citeCount = 0;
      const textWithCites = collection
        .map((c) => {
          // separate the cites into those with a position and those without
          // sort by end_index (to allow for numbering to not affect indexes)
          // Type guard function to check if cited_text is a range
          const positionalCites = (c.citations ?? [])
            .filter(isCitationWithRange)
            .sort((a, b) => b.cited_text[1] - a.cited_text[1]);

          const endCites = c.citations?.filter(
            (citation) => !isCitationWithRange(citation),
          );

          // Process cites with positions
          let textWithCites = c.text;
          for (let i = 0; i < positionalCites.length; i++) {
            const end_index = positionalCites[i].cited_text[1];

            textWithCites =
              textWithCites.slice(0, end_index) +
              `<sup>${positionalCites.length - i}</sup>` +
              textWithCites.slice(end_index);
          }
          citeCount = citeCount + positionalCites.length;

          // Process cites without positions (they just attach to the end of the content)
          const citeText = endCites?.map((_citation) => `${++citeCount}`);
          let inlineCites = "";
          if (citeText && citeText.length > 0) {
            inlineCites = `<sup>${citeText.join(",")}</sup>`;
          }
          return (textWithCites || "") + inlineCites;
        })
        .join("");

      // Flatten the text from the collection into a single text content
      result.push({
        type: "text",
        text: textWithCites,
        refusal: null,
        internal: null,
        citations: filteredCitations,
      });
      collection.length = 0;
    }
  };

  for (const content of contents) {
    if (typeof content === "string") {
      // this shouldn't happen, but if it does
      // just convert it to a text content
      result.push({
        type: "text",
        text: content,
        refusal: null,
        internal: null,
        citations: null,
      });
      continue;
    }

    if (content.type === "text") {
      // Collect text until we hit a  non-text content
      collection.push(content);
      continue;
    } else {
      // collect any text content before this non-text content
      collect();
      result.push(content);
    }
  }

  // collect any remaining text content
  collect();

  return result;
};

// This is a helper that makes Omit<> work with a union type by distributing
// the omit over the union members.
export type DistributiveOmit<TObj, TKey extends PropertyKey> = TObj extends any
  ? Omit<TObj, TKey>
  : never;

/** Type guard that allows narrowing down to Citations whose `cited_text` is a range */
const isCitationWithRange = (
  citation: Citation,
): citation is DistributiveOmit<Citation, "cited_text"> & {
  cited_text: [number, number];
} => Array.isArray(citation.cited_text);
