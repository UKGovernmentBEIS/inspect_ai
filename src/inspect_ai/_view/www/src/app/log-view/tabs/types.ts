import { ReactNode } from "react";
import { SampleSummary } from "../../../client/api/types";

export interface SampleListItem {
  data: SampleSummary;
  answer: string;
  scoresRendered: ReactNode[];
  completed: boolean;
}
