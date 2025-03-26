import clsx from "clsx";
import { FC, ReactNode } from "react";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataView } from "../../metadata/MetaDataView";
import { Input2, Input5, Result2, SubtaskEvent } from "../../types/log";
import { EventPanel } from "./event/EventPanel";
import { formatTiming, formatTitle } from "./event/utils";
import styles from "./SubtaskEventView.module.css";
import { TranscriptView } from "./TranscriptView";

interface SubtaskEventViewProps {
  id: string;
  event: SubtaskEvent;
  depth: number;
  className?: string | string[];
}

/**
 * Renders the StateEventView component.
 */
export const SubtaskEventView: FC<SubtaskEventViewProps> = ({
  id,
  event,
  depth,
  className,
}) => {
  const body: ReactNode[] = [];
  if (event.type === "fork") {
    body.push(
      <div title="Summary" className={clsx(styles.summary)}>
        <div className={clsx("text-style-label")}>Inputs</div>
        <div className={clsx(styles.summaryRendered)}>
          <Rendered values={event.input} />
        </div>
        <div className={clsx("text-style-label")}>Transcript</div>
        {event.events.length > 0 ? (
          <TranscriptView
            id={`${id}-subtask`}
            data-name="Transcript"
            events={event.events}
            depth={depth + 1}
          />
        ) : (
          <None />
        )}
      </div>,
    );
  } else {
    body.push(
      <SubtaskSummary
        data-name="Summary"
        input={event.input}
        result={event.result}
      />,
    );
    if (event.events.length > 0) {
      body.push(
        <TranscriptView
          id={`${id}-subtask`}
          data-name="Transcript"
          events={event.events}
          depth={depth + 1}
        />,
      );
    }
  }

  // Is this a traditional subtask or a fork?
  const type = event.type === "fork" ? "Fork" : "Subtask";
  return (
    <EventPanel
      id={id}
      className={className}
      title={formatTitle(
        `${type}: ${event.name}`,
        undefined,
        event.working_time,
      )}
      subTitle={formatTiming(event.timestamp, event.working_start)}
      collapse={false}
    >
      {body}
    </EventPanel>
  );
};

interface SubtaskSummaryProps {
  input: Input2 | Input5;
  result: Result2;
}
/**
 * Renders the StateEventView component.
 */
const SubtaskSummary: FC<SubtaskSummaryProps> = ({ input, result }) => {
  const output = typeof result === "object" ? result : { result };
  return (
    <div className={clsx(styles.subtaskSummary)}>
      <div className={clsx("text-style-label")}>Input</div>
      <div className={clsx("text-size-large", styles.subtaskLabel)}></div>
      <div className={clsx("text-style-label")}>Output</div>
      {input ? <Rendered values={input} /> : undefined}
      <div className={clsx("text-size-title-secondary", styles.subtaskLabel)}>
        <i className={ApplicationIcons.arrows.right} />
      </div>
      <div>
        <Rendered values={output} />
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
const Rendered: FC<RenderedProps> = ({ values }) => {
  if (Array.isArray(values)) {
    return values.map((val) => {
      return <Rendered values={val} />;
    });
  } else if (values && typeof values === "object") {
    if (Object.keys(values).length === 0) {
      return <None />;
    } else {
      return <MetaDataView entries={values as Record<string, unknown>} />;
    }
  } else {
    return values;
  }
};

const None: FC = () => {
  return (
    <span className={clsx("text-size-small", "text-style-secondary")}>
      [None]
    </span>
  );
};
