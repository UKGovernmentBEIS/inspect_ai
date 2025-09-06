import { CSSProperties, forwardRef } from "react";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { Preformatted } from "../../components/Preformatted";
import { useStore } from "../../state/store";

interface RenderedTextProps {
  markdown: string;
  style?: CSSProperties;
  className?: string | string[];
  forceRender?: boolean;
}

export const RenderedText = forwardRef<HTMLDivElement, RenderedTextProps>(
  ({ markdown, style, className, forceRender }, ref) => {
    const displayMode = useStore((state) => state.app.displayMode);
    if (forceRender || displayMode === "rendered") {
      return (
        <MarkdownDiv
          ref={ref}
          markdown={markdown}
          style={style}
          className={className}
        />
      );
    } else {
      return (
        <Preformatted
          ref={ref}
          text={markdown}
          style={style}
          className={className}
        />
      );
    }
  },
);
