import { ReactNode, RefObject } from "react";

export interface TabDescriptor {
  id: string;
  scrollable: boolean;
  scrollRef?: RefObject<HTMLDivElement>;
  label: string;
  content: () => ReactNode;
  tools?: () => ReactNode[] | undefined;
}
