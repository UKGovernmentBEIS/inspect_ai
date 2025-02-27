import { ApplicationIcons } from "../../appearance/icons";
import ExpandablePanel from "../../components/ExpandablePanel";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { MetaDataGrid } from "../../metadata/MetaDataGrid";
import { SandboxEvent } from "../../types/log";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";
import { TranscriptEventState } from "./types";

import clsx from "clsx";
import { FC } from "react";
import styles from "./SandboxEventView.module.css";
import { formatTiming } from "./event/utils";

interface SandboxEventViewProps {
  id: string;
  event: SandboxEvent;
  eventState: TranscriptEventState;
  setEventState: (state: TranscriptEventState) => void;
  className?: string | string[];
}

/**
 * Renders the SandboxEventView component.
 */
export const SandboxEventView: FC<SandboxEventViewProps> = ({
  id,
  event,
  eventState,
  setEventState,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      className={className}
      title={`Sandbox: ${event.action}`}
      icon={ApplicationIcons.sandbox}
      subTitle={formatTiming(event.timestamp, event.working_start)}
      selectedNav={eventState.selectedNav || ""}
      setSelectedNav={(selectedNav) => {
        setEventState({ ...eventState, selectedNav });
      }}
      collapsed={eventState.collapsed}
      setCollapsed={(collapsed) => {
        setEventState({ ...eventState, collapsed });
      }}
    >
      {event.action === "exec" ? (
        <ExecView event={event} />
      ) : event.action === "read_file" ? (
        <ReadFileView event={event} />
      ) : (
        <WriteFileView event={event} />
      )}
    </EventPanel>
  );
};

interface ExecViewProps {
  event: SandboxEvent;
}

const ExecView: FC<ExecViewProps> = ({ event }) => {
  if (event.cmd === null) {
    return undefined;
  }
  const cmd = event.cmd;
  const options = event.options;
  const input = event.input;
  const result = event.result;
  const output = event.output;

  return (
    <div className={clsx(styles.exec)}>
      <EventSection title={`Command`}>
        <div className={clsx(styles.twoColumn)}>
          <pre className={clsx(styles.wrapPre)}>{cmd}</pre>
          <pre className={clsx(styles.wrapPre)}>
            {input !== null ? input?.trim() : undefined}
          </pre>

          {options !== null ? (
            <EventSection title={`Options`}>
              <MetaDataGrid
                entries={options as Record<string, unknown>}
                plain={true}
              />
            </EventSection>
          ) : undefined}
        </div>
      </EventSection>
      <EventSection title={`Result`}>
        {output ? (
          <ExpandablePanel collapse={false}>
            <MarkdownDiv markdown={output} />
          </ExpandablePanel>
        ) : undefined}
        <div className={clsx(styles.result)}>Exited with code {result}</div>
      </EventSection>
    </div>
  );
};

interface ReadFileViewProps {
  event: SandboxEvent;
}

const ReadFileView: FC<ReadFileViewProps> = ({ event }) => {
  if (event.file === null) {
    return undefined;
  }
  const file = event.file;
  const output = event.output;
  return <FileView file={file} contents={output?.trim()} />;
};

interface WriteFileViewProps {
  event: SandboxEvent;
}

const WriteFileView: FC<WriteFileViewProps> = ({ event }) => {
  if (event.file === null) {
    return undefined;
  }
  const file = event.file;
  const input = event.input;

  return <FileView file={file} contents={input?.trim()} />;
};

interface FileViewProps {
  file: string;
  contents?: string;
}

const FileView: FC<FileViewProps> = ({ file, contents }) => {
  return (
    <div>
      <EventSection title="File">
        <pre className={clsx(styles.fileLabel)}>{file}</pre>
      </EventSection>

      {contents ? (
        <EventSection title="Contents">
          <ExpandablePanel collapse={false}>
            <pre>{contents}</pre>
          </ExpandablePanel>
        </EventSection>
      ) : undefined}
    </div>
  );
};
