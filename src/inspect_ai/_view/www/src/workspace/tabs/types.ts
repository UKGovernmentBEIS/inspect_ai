import { SampleSummary } from "../../api/types";

export interface SampleListItem {
  label: string;
  index: number;
  number: number;
  data: SampleSummary;
  type: "sample";
}

export interface SeparatorListItem {
  label: string;
  index: number;
  number: number;
  data: string;
  type: "separator";
}

export type ListItem = SampleListItem | SeparatorListItem;
