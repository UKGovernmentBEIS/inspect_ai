import clsx from "clsx";
import { Fragment } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataView } from "../../metadata/MetaDataView";
import { Input2, Input4, Result1, SubtaskEvent } from "../../types/log";
import { formatDateTime } from "../../utils/format";
import { EventPanel } from "./event/EventPanel";
import styles from "./SubtaskEventView.module.css";
import { TranscriptView } from "./TranscriptView";
import { TranscriptEventState } from "./types";

interface SubtaskEventViewProps {
  id: string;
  event: SubtaskEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  depth: number;
  className?: string | string[];
}

/**
 * Renders the StateEventView component.
 */
export const SubtaskEventView: React.FC<SubtaskEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  depth,
  className,
}) => {
  // Render Forks specially

  const transcript =
    event.events.length > 0 ? (
      <TranscriptView
        id={`${id}-subtask`}
        data-name="Transcript"
        events={event.events}
        depth={depth + 1}
      />
    ) : (
      ""
    );

  const body =
    event.type === "fork" ? (
      <div title="Summary" className={clsx(styles.summary)}>
        <div className={clsx("text-style-label")}>Inputs</div>
        <div className={clsx(styles.summaryRendered)}>
          <Rendered values={event.input} />
        </div>
        <div className={clsx("text-style-label")}>Transcript</div>
        {transcript}
      </div>
    ) : (
      <Fragment>
        <SubtaskSummary
          data-name="Summary"
          input={event.input}
          result={event.result}
        />
        {transcript}
      </Fragment>
    );

  // Is this a traditional subtask or a fork?
  const type = event.type === "fork" ? "Fork" : "Subtask";
  return (
    <EventPanel
      id={id}
      className={className}
      title={`${type}: ${event.name}`}
      subTitle={formatDateTime(new Date(event.timestamp))}
      collapse={false}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      {body}
    </EventPanel>
  );
};

interface SubtaskSummaryProps {
  input: Input2 | Input4;
  result: Result1;
}
/**
 * Renders the StateEventView component.
 */
const SubtaskSummary: React.FC<SubtaskSummaryProps> = ({ input, result }) => {
  result = typeof result === "object" ? result : { result };
  return (
    <div className={clsx(styles.subtaskSummary)}>
      <div className={clsx("text-style-label")}>Input</div>
      <div className={clsx("text-size-large", styles.subtaskLabel)}></div>
      <div className={clsx("text-style-label")}>Output</div>
      <Rendered values={input} />
      <div className={clsx("text-size-title-secondary", styles.subtaskLabel)}>
        <i className={ApplicationIcons.arrows.right} />
      </div>
      <div>
        <Rendered values={result} />
      </div>
    </div>
  );
};

interface RenderedProps {
  values: Array<unknown> | Object | string | number;
}

/**
 * Recursively renders content based on the type of `values`.
value.
 */
const Rendered: React.FC<RenderedProps> = ({ values }) => {
  if (Array.isArray(values)) {
    return values.map((val) => {
      return <Rendered values={val} />;
    });
  } else if (values && typeof values === "object") {
    return <MetaDataView entries={values as Record<string, unknown>} />;
  } else {
    return values;
  }
};
