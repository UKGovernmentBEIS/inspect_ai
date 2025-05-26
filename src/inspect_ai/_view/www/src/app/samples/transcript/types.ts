import {
  ApprovalEvent,
  Changes,
  ErrorEvent,
  InfoEvent,
  InputEvent,
  LoggerEvent,
  ModelEvent,
  SampleInitEvent,
  SampleLimitEvent,
  SandboxEvent,
  ScoreEvent,
  SpanBeginEvent,
  SpanEndEvent,
  StateEvent,
  StepEvent,
  StoreEvent,
  SubtaskEvent,
  ToolEvent,
} from "../../../@types/log";

export interface StateManager {
  scope: string;
  getState(): object;
  initializeState(state: object): void;
  applyChanges(changes: Changes): object;
}

export const kTranscriptCollapseScope = "transcript-collapse";

export type EventType =
  | SampleInitEvent
  | SampleLimitEvent
  | StateEvent
  | StoreEvent
  | ModelEvent
  | LoggerEvent
  | InfoEvent
  | StepEvent
  | SubtaskEvent
  | ScoreEvent
  | ToolEvent
  | InputEvent
  | ErrorEvent
  | ApprovalEvent
  | SandboxEvent
  | SpanBeginEvent
  | SpanEndEvent;

export class EventNode<T extends EventType = EventType> {
  id: string;
  event: T;
  children: EventNode<EventType>[] = [];
  depth: number;

  constructor(id: string, event: T, depth: number) {
    this.id = id;
    this.event = event;
    this.depth = depth;
  }
}

export interface TranscriptEventState {
  selectedNav?: string;
  collapsed?: boolean;
}

export type TranscriptState = Record<string, TranscriptEventState>;
