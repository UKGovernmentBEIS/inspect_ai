import { SandboxEvent } from "../../../@types/log";
import ExpandablePanel from "../../../components/ExpandablePanel";
import { MarkdownDiv } from "../../../components/MarkdownDiv";
import { ApplicationIcons } from "../../appearance/icons";
import { MetaDataGrid } from "../../content/MetaDataGrid";
import { EventPanel } from "./event/EventPanel";
import { EventSection } from "./event/EventSection";

import clsx from "clsx";
import { FC } from "react";
import styles from "./SandboxEventView.module.css";
import { formatTiming } from "./event/utils";

interface SandboxEventViewProps {
  id: string;
  event: SandboxEvent;
  className?: string | string[];
}

/**
 * Renders the SandboxEventView component.
 */
export const SandboxEventView: FC<SandboxEventViewProps> = ({
  id,
  event,
  className,
}) => {
  return (
    <EventPanel
      id={id}
      className={className}
      title={`Sandbox: ${event.action}`}
      icon={ApplicationIcons.sandbox}
      subTitle={formatTiming(event.timestamp, event.working_start)}
    >
      {event.action === "exec" ? (
        <ExecView id={`${id}-exec`} event={event} />
      ) : event.action === "read_file" ? (
        <ReadFileView id={`${id}-read-file`} event={event} />
      ) : (
        <WriteFileView id={`${id}-write-file`} event={event} />
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
  const output = event.output;

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
      <EventSection title={`Result`}>
        {output ? (
          <ExpandablePanel id={`${id}-output`} collapse={false}>
            <MarkdownDiv markdown={output} />
          </ExpandablePanel>
        ) : undefined}
        {result !== 0 ? (
          <div className={clsx(styles.result)}>Exited with code {result}</div>
        ) : undefined}
      </EventSection>
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
