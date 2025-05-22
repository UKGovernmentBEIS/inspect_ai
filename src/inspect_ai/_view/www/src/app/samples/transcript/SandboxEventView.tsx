import { SandboxEvent } from "../../../@types/log";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";

import clsx from "clsx";
import { FC } from "react";
import { RenderedContent } from "../../content/RenderedContent";
import styles from "./SandboxEventView.module.css";
import { formatTiming } from "./event/utils";
import { EventNode } from "./types";

interface SandboxEventViewProps {
  eventNode: EventNode<SandboxEvent>;
  className?: string | string[];
}

/**
 * Renders the SandboxEventView component.
 */
export const SandboxEventView: FC<SandboxEventViewProps> = ({
  eventNode,
  className,
}) => {
  const event = eventNode.event;
  return (
    <EventPanel
      eventNodeId={eventNode.id}
      depth={eventNode.depth}
      className={className}
      title={`Sandbox: ${event.action}`}
      icon={ApplicationIcons.sandbox}
      subTitle={formatTiming(event.timestamp, event.working_start)}
    >
      {event.action === "exec" ? (
        <ExecView id={`${eventNode.id}-exec`} event={event} />
      ) : event.action === "read_file" ? (
        <ReadFileView id={`${eventNode.id}-read-file`} event={event} />
      ) : (
        <WriteFileView id={`${eventNode.id}-write-file`} event={event} />
      )}
    </EventPanel>
  );
};

interface ExecViewProps {
  id: string;
  event: SandboxEvent;
}

const ExecView: FC<ExecViewProps> = ({ id, event }) => {
  if (event.cmd === null) {
    return undefined;
  }
  const cmd = event.cmd;
  const options = event.options;
  const input = event.input;
  const result = event.result;
  const output = event.output ? event.output.trim() : undefined;

  return (
    <div className={clsx(styles.exec)}>
      <EventSection title={`Command`}>
        <div className={clsx(styles.twoColumn)}>
          <pre className={clsx(styles.wrapPre)}>{cmd}</pre>
          <pre className={clsx(styles.wrapPre)}>
            {input !== null ? input?.trim() : undefined}
          </pre>

          {options !== null && Object.keys(options).length > 0 ? (
            <EventSection title={`Options`}>
              <MetaDataGrid
                entries={options as Record<string, unknown>}
                plain={true}
              />
            </EventSection>
          ) : undefined}
        </div>
      </EventSection>
      {output || (result !== null && result !== 0) ? (
        <EventSection title={`Result`}>
          {output ? (
            <ExpandablePanel id={`${id}-output`} collapse={false}>
              <RenderedContent
                id={`${id}-output-content`}
                entry={{ name: "sandbox_output", value: output }}
              />
            </ExpandablePanel>
          ) : undefined}
          {result !== 0 ? (
            <div className={clsx(styles.result, "text-size-base")}>
              (exited with code {result})
            </div>
          ) : undefined}
        </EventSection>
      ) : undefined}
    </div>
  );
};

interface ReadFileViewProps {
  id: string;
  event: SandboxEvent;
}

const ReadFileView: FC<ReadFileViewProps> = ({ id, event }) => {
  if (event.file === null) {
    return undefined;
  }
  const file = event.file;
  const output = event.output;
  return <FileView id={id} file={file} contents={output?.trim()} />;
};

interface WriteFileViewProps {
  id: string;
  event: SandboxEvent;
}

const WriteFileView: FC<WriteFileViewProps> = ({ id, event }) => {
  if (event.file === null) {
    return undefined;
  }
  const file = event.file;
  const input = event.input;

  return <FileView id={id} file={file} contents={input?.trim()} />;
};

interface FileViewProps {
  id: string;
  file: string;
  contents?: string;
}

const FileView: FC<FileViewProps> = ({ id, file, contents }) => {
  return (
    <div>
      <EventSection title="File">
        <pre className={clsx(styles.fileLabel)}>{file}</pre>
      </EventSection>

      {contents ? (
        <EventSection title="Contents">
          <ExpandablePanel id={`${id}-file`} collapse={false}>
            <pre>{contents}</pre>
          </ExpandablePanel>
        </EventSection>
      ) : undefined}
    </div>
  );
};
