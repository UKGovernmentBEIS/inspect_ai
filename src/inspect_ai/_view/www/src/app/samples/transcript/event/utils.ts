import {
  formatDateTime,
  formatNumber,
  formatTime,
} from "../../../../utils/format";

export const formatTiming = (timestamp: string, working_start?: number) => {
  if (working_start) {
    return `${formatDateTime(new Date(timestamp))}\n@ working time: ${formatTime(working_start)}`;
  } else {
    return formatDateTime(new Date(timestamp));
  }
};

export const formatTitle = (
  title: string,
  total_tokens?: number,
  working_start?: number | null,
) => {
  const subItems = [];
  if (total_tokens) {
    subItems.push(`${formatNumber(total_tokens)} tokens`);
  }
  if (working_start) {
    subItems.push(`${formatTime(working_start)}`);
  }
  const subtitle = subItems.length > 0 ? ` (${subItems.join(", ")})` : "";
  return `${title}${subtitle}`;
};
