import { Citations } from "../../../@types/log";

export type ChatViewToolCallStyle = "compact" | "complete" | "omit";

export type Citation = NonNullable<Citations>[number];
