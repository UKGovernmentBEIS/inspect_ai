import clsx from "clsx";

import { FC, ReactNode } from "react";
import {
  ContentAudio,
  ContentData,
  ContentImage,
  ContentReasoning,
  ContentText,
  ContentVideo,
  Format2,
  Format3,
} from "../../../@types/log";
import { ContentTool } from "../../../app/types";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { ContentDataView } from "./content-data/ContentDataView";
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
            format: null,
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
      format: null,
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
    render: (key, content, isLast, context) => {
      // The context provides a way to share context between different
      // rendering. In this case, we'll use it to keep track of citations
      const c = content as ContentText;
      const citeOffset = (context.citeOffset as number) || 0;
      const cites = citations(c);

      if (!c.text && !cites.length) {
        return undefined;
      }

      // Generate a superscript mark for each citation (using a message level counter)
      // and append it to the text. Add the citation to the context for later rendering / use.
      const citeText = cites.map(
        (_citation, index) => `${citeOffset + index + 1}`,
      );
      let inlineCites = "";
      if (citeText.length > 0) {
        inlineCites = `<sup>${citeText.join(",")}</sup>`;
      }
      context.citeOffset = citeOffset + cites.length;
      context.citations.push(...cites);

      return (
        <>
          <MarkdownDiv
            key={key}
            markdown={(c.text || "") + " " + inlineCites}
            className={isLast ? "no-last-para-padding" : ""}
          />
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
const mimeTypeForFormat = (format: Format2 | Format3): string => {
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

const citations = (contents: ContentText): Citation[] => {
  const results: Citation[] = [];
  for (const citation of contents.citations || []) {
    if (citation.url === undefined || citation.cited_text === undefined) {
      console.error("Invalid citation format", citation);
    }
    results.push(citation as Citation);
  }
  return results;
};

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
  let collecting = false;
  const collection: ContentText[] = [];

  const collect = () => {
    if (collection.length > 0) {
      // Flatten the citations from the collection
      const citations = collection
        .flatMap((c) => c.citations || [])
        .filter((c, index, self) => {
          // remove duplicates
          return (
            self.findIndex(
              (item) => item.url === c.url && item.cited_text === c.cited_text,
            ) === index
          );
        });

      // Flatten the text from the collection into a single text content
      result.push({
        type: "text",
        text: collection.map((c) => c.text).join(" "),
        refusal: null,
        internal: null,
        format: null,
        citations: citations,
      });
      collection.length = 0;
      collecting = false;
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
        format: null,
        citations: null,
      });
      continue;
    }

    if (content.type === "text") {
      // Collect text until we hit a  non-text content or a text with citations
      collection.push(content);
      if (content.citations && content.citations.length > 0) {
        collect();
      }
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
