import { ReactNode } from "react";
import { SampleSummary } from "../../../client/api/types";

export interface SampleListItem {
  sampleId: string | number;
  sampleEpoch: number;
  label: string;
  index: number;
  number: number;
  answer: string;
  scoresRendered: ReactNode[];
  data: SampleSummary;
  type: "sample";
  completed: boolean;
}

export interface SeparatorListItem {
  label: string;
  index: number;
  number: number;
  data: string;
  type: "separator";
}

export type ListItem = SampleListItem | SeparatorListItem;
