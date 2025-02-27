import { formatDateTime, formatTime } from "../../../utils/format";

export const formatTiming = (timestamp: string, working_start?: number) => {
  if (working_start) {
    return `${formatDateTime(new Date(timestamp))}\nAt working time: ${formatTime(working_start)}`;
  } else {
    return formatDateTime(new Date(timestamp));
  }
};
