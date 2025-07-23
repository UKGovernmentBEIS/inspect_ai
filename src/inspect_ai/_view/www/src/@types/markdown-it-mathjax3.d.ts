declare module "markdown-it-mathjax3" {
  import MarkdownIt from "markdown-it";

  interface MathjaxOptions {
    tex?: {
      inlineMath?: [string, string][];
      displayMath?: [string, string][];
      tags?: string;
      tagSide?: string;
      tagIndent?: string;
      useLabelIds?: boolean;
      multlineWidth?: string;
      maxMacros?: number;
      maxBuffer?: number;
    };
    svg?: {
      fontCache?: string;
      localID?: string | null;
    };
    chtml?: {
      scale?: number;
      minScale?: number;
      matchFontHeight?: boolean;
      fontURL?: string;
    };
    startup?: {
      typeset?: boolean;
      ready?: () => void;
    };
  }

  const markdownItMathjax3: (md: MarkdownIt, options?: MathjaxOptions) => void;

  export default markdownItMathjax3;
}
