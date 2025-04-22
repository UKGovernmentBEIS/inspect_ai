import { ReactNode } from "react";
import { Value2 } from "../../../@types/log";
import { ScoreLabel } from "../../../app/types";
import { BasicSampleData } from "../../../client/api/types";

export interface EvalDescriptor {
  scores: ScoreLabel[];
  scoreDescriptor: (scoreLabel: ScoreLabel) => ScoreDescriptor;
  scorerDescriptor: (
    sample: BasicSampleData,
    scoreLabel: ScoreLabel,
  ) => ScorerDescriptor;
  score: (
    sample: BasicSampleData,
    scoreLabel?: ScoreLabel,
  ) => SelectedScore | undefined;
  scoreAnswer: (
    sample: BasicSampleData,
    scorer: ScoreLabel,
  ) => string | undefined;
}

export interface ScorerDescriptor {
  metadata: () => Record<string, unknown>;
  explanation: () => string;
  answer: () => string;
  scores: () => Array<{ name: string; rendered: () => ReactNode }>;
}

export interface ScoreDescriptor {
  scoreType: string;
  categories?: Array<Object>;
  min?: number;
  max?: number;
  compare: (a: SelectedScore, b: SelectedScore) => number;
  render: (score: Value2) => ReactNode;
}

export interface SelectedScore {
  value?: Value2;
  render: () => ReactNode;
}

export interface MessageShape {
  raw: MessageShapeData;
  normalized: MessageShapeData;
}

export interface MessageShapeData {
  id: number;
  input: number;
  target: number;
  answer: number;
  limit: number;
  retries: number;
  score: number;
}
