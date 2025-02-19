// @ts-check
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import { Messages, SampleInitEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { toArray } from "../../utils/type";
import { ChatView } from "../chat/ChatView";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";
import { TranscriptEventState } from "./types";

import styles from "./SampleInitEventView.module.css";

interface SampleInitEventViewProps {
  id: string;
  event: SampleInitEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the SampleInitEventView component.
 */
export const SampleInitEventView: React.FC<SampleInitEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  const stateObj = event.state as Record<string, unknown>;

  const sections = [];

  if (event.sample.files && Object.keys(event.sample.files).length > 0) {
    sections.push(
      <EventSection title="Files" key={`sample-${id}-init-files`}>
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
      <EventSection title="Setup" key={`sample-${id}-init-setup`}>
        <pre className={styles.code}>
          <code className="sourceCode">{event.sample.setup}</code>
        </pre>
      </EventSection>,
    );
  }

  return (
    <EventPanel
      id={id}
      className={className}
      title="Sample"
      icon={ApplicationIcons.sample}
      subTitle={formatDateTime(new Date(event.timestamp))}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
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
          <EventSection title="Target">
            {toArray(event.sample.target).map((target) => {
              return <div key={target}>{target}</div>;
            })}
          </EventSection>
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
