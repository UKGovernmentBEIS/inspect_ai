import { SampleSummary } from "../../../client/api/types";

export interface SampleListItem {
  data: SampleSummary;
  answer: string;
  completed: boolean;
}
