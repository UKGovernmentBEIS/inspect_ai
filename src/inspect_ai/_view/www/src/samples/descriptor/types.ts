import { ReactNode } from "react";
import { BasicSampleData, SampleSummary } from "../../api/types";
import { ScoreLabel } from "../../types";
import { Value2 } from "../../types/log";

export interface EvalDescriptor {
  epochs: number;
  samples: SampleSummary[];
  scores: ScoreLabel[];
  scoreDescriptor: (scoreLabel: ScoreLabel) => ScoreDescriptor;
  scorerDescriptor: (
    sample: BasicSampleData,
    scoreLabel: ScoreLabel,
  ) => ScorerDescriptor;
  score: (
    sample: BasicSampleData,
    scoreLabel: ScoreLabel,
  ) => SelectedScore | undefined;
  scoreAnswer: (sample: BasicSampleData, scorer: string) => string | undefined;
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
  score: number;
}
