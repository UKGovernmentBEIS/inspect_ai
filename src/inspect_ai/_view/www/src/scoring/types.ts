export interface MetricSummary {
  name: string;
  params?: {};
  value: number;
}

export interface ScoreSummary {
  scorer: string;
  reducer?: string;
  metrics: MetricSummary[];
}
