import { ReactNode } from "react";
import { SampleSummary } from "../../../client/api/types";

export interface SampleListItem {
  label: string;
  index: number;
  number: number;
  answer: string;
  scoreRendered: ReactNode;
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
