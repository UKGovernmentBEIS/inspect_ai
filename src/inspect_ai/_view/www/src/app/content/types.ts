import { ReactNode } from "react";

export const Buckets = {
  first: 0,
  intermediate: 10,
  final: 1000,
};

export interface RenderOptions {
  renderString: "pre" | "markdown";
}

export interface ContentRenderer {
  bucket: number;
  canRender: (content: any) => boolean;
  render: (
    id: string,
    content: any,
    options: RenderOptions,
  ) => {
    rendered: string | number | bigint | boolean | object | ReactNode | null;
  };
}
