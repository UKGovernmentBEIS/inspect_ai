// @ts-check
import { Messages, SampleInitEvent } from "../../../@types/log";
import { formatDateTime } from "../../../utils/format";
import { toArray } from "../../../utils/type";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { ChatView } from "../chat/ChatView";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";

import clsx from "clsx";
import { FC } from "react";
import styles from "./SampleInitEventView.module.css";
import { EventNode } from "./types";

interface SampleInitEventViewProps {
  eventNode: EventNode<SampleInitEvent>;
  className?: string | string[];
}

/**
 * Renders the SampleInitEventView component.
 */
export const SampleInitEventView: FC<SampleInitEventViewProps> = ({
  eventNode,
  className,
}) => {
  const event = eventNode.event;
  const stateObj = event.state as Record<string, unknown>;

  const sections = [];

  if (event.sample.files && Object.keys(event.sample.files).length > 0) {
    sections.push(
      <EventSection title="Files" key={`event-${eventNode.id}`}>
        {Object.keys(event.sample.files).map((file) => {
          return (
            <pre key={`sample-init-file-${file}`} className={styles.noMargin}>
              {file}
            </pre>
          );
        })}
      </EventSection>,
    );
  }

  if (event.sample.setup) {
    sections.push(
      <EventSection title="Setup" key={`${eventNode.id}-section-setup`}>
        <pre className={styles.code}>
          <code className="sourceCode">{event.sample.setup}</code>
        </pre>
      </EventSection>,
    );
  }

  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      className={className}
      title="Sample"
      icon={ApplicationIcons.sample}
      subTitle={formatDateTime(new Date(event.timestamp))}
    >
      <div data-name="Sample" className={styles.sample}>
        <ChatView messages={stateObj["messages"] as Messages} />
        <div>
          {event.sample.choices
            ? event.sample.choices.map((choice, index) => {
                return (
                  <div key={`$choice-{choice}`}>
                    {String.fromCharCode(65 + index)}) {choice}
                  </div>
                );
              })
            : ""}
          {sections.length > 0 ? (
            <div className={styles.section}>{sections}</div>
          ) : (
            ""
          )}
          {event.sample.target ? (
            <EventSection title="Target">
              {toArray(event.sample.target).map((target) => {
                return (
                  <div key={target} className={clsx("text-size-base")}>
                    {target}
                  </div>
                );
              })}
            </EventSection>
          ) : undefined}
        </div>
      </div>
      {event.sample.metadata &&
      Object.keys(event.sample.metadata).length > 0 ? (
        <MetaDataGrid
          data-name="Metadata"
          className={styles.metadata}
          entries={event.sample.metadata}
        />
      ) : (
        ""
      )}
    </EventPanel>
  );
};
