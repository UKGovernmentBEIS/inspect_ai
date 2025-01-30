import { ReactNode, RefObject } from "react";

export interface TabDescriptor {
  id: string;
  scrollable: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  label: string;
  content: () => ReactNode;
  tools?: () => ReactNode[] | undefined;
}
