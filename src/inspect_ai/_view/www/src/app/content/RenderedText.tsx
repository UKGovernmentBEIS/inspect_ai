import { CSSProperties, ForwardedRef, forwardRef } from "react";
import { MarkdownDiv } from "../../components/MarkdownDiv";
import { Preformatted } from "../../components/Preformatted";
import { useStore } from "../../state/store";

interface RenderedTextProps {
  markdown: string;
  style?: CSSProperties;
  className?: string | string[];
  forceRender?: boolean;
  omitMedia?: boolean;
}

export const RenderedText = forwardRef<
  HTMLDivElement | HTMLPreElement,
  RenderedTextProps
>(({ markdown, style, className, forceRender, omitMedia }, ref) => {
  const displayMode = useStore((state) => state.app.displayMode);
  if (forceRender || displayMode === "rendered") {
    return (
      <MarkdownDiv
        ref={ref as ForwardedRef<HTMLDivElement>}
        markdown={markdown}
        style={style}
        className={className}
        omitMedia={omitMedia}
      />
    );
  } else {
    return (
      <Preformatted
        ref={ref as ForwardedRef<HTMLPreElement>}
        text={markdown}
        style={style}
        className={className}
      />
    );
  }
});
