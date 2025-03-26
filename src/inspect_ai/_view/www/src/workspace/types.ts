import { ComponentType, ReactNode, RefObject } from "react";

export interface TabDescriptor<P> {
  id: string;
  scrollable: boolean;
  scrollRef?: RefObject<HTMLDivElement | null>;
  label: string;
  component: ComponentType<P>;
  componentProps: P;
  tools?: () => ReactNode[] | undefined;
}
