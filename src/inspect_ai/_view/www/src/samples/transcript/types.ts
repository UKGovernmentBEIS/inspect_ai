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
  StateEvent,
  StepEvent,
  StoreEvent,
  SubtaskEvent,
  ToolEvent,
} from "../../types/log";

export interface StateManager {
  scope: string;
  getState(): object;
  initializeState(state: object): void;
  applyChanges(changes: Changes): object;
}

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
  | SandboxEvent;

export class EventNode {
  event: EventType;
  children: EventNode[] = [];
  depth: number;

  constructor(event: EventType, depth: number) {
    this.event = event;
    this.depth = depth;
  }
}

export interface TranscriptEventState {
  selectedNav?: string;
  collapsed?: boolean;
}

export type TranscriptState = Record<string, TranscriptEventState>;
