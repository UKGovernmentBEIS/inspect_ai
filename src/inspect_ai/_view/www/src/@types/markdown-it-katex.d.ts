declare module "markdown-it-katex" {
  import MarkdownIt from "markdown-it";

  interface KatexOptions {
    throwOnError?: boolean;
    errorColor?: string;
    macros?: Record<string, string>;
    fleqn?: boolean;
    trust?: boolean;
    output?: "html" | "htmlAndMathml" | "mathml";
    minRuleThickness?: number;
    colorIsTextColor?: boolean;
    maxSize?: number;
    maxExpand?: number;
    strict?: boolean | string | Function;
  }

  const markdownItKatex: (md: MarkdownIt, options?: KatexOptions) => void;

  export default markdownItKatex;
}
