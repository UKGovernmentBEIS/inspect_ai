import {
  escapeHtmlCharacters,
  protectBackslashesInLatex,
  restoreBackslashesForLatex,
  unescapeHtmlForMath,
  getMarkdownInstance,
} from "../../components/markdownRendering";

/**
 * Simulate the async rendering pipeline from MarkdownDiv.
 * This mirrors the steps in the renderQueue.enqueue callback.
 */
function renderPipeline(markdown: string, omitMath = false): string {
  const protectedContent = protectBackslashesInLatex(markdown);
  const escaped = escapeHtmlCharacters(protectedContent);
  const preparedForMarkdown = restoreBackslashesForLatex(escaped);

  const md = getMarkdownInstance(false, omitMath);
  return md.render(preparedForMarkdown);
}

describe("MarkdownDiv XSS security", () => {
  describe("script injection in LaTeX blocks", () => {
    it("should not produce raw <script> tags from inline math", () => {
      const result = renderPipeline("$<script>alert(1)</script>$");
      expect(result).not.toContain("<script>");
      expect(result).not.toContain("</script>");
    });

    it("should not produce raw <script> tags from block math", () => {
      const result = renderPipeline("$$<script>alert(1)</script>$$");
      expect(result).not.toContain("<script>");
      expect(result).not.toContain("</script>");
    });
  });

  describe("event handler injection in LaTeX blocks", () => {
    it("should not produce raw <img> with onerror from inline math", () => {
      const result = renderPipeline('$<img src=x onerror="alert(1)">$');
      expect(result).not.toContain("<img");
      expect(result).not.toContain("onerror");
    });

    it("should not produce raw <img> with onerror from block math", () => {
      const result = renderPipeline('$$<img src=x onerror="alert(1)">$$');
      expect(result).not.toContain("<img");
      expect(result).not.toContain("onerror");
    });
  });

  describe("script injection outside LaTeX", () => {
    it("should escape <script> tags in plain text", () => {
      const result = renderPipeline("<script>alert(1)</script>");
      expect(result).not.toContain("<script>");
    });

    it("should escape event handlers in plain text", () => {
      const result = renderPipeline('<img src=x onerror="alert(1)">');
      // The text "onerror" may appear as escaped text, but no raw <img> tag
      expect(result).not.toContain("<img");
    });
  });

  describe("legitimate LaTeX still renders", () => {
    it("should render inline math with backslashes", () => {
      const result = renderPipeline("$\\frac{1}{2}$");
      // MathJax should process this — output should contain mjx-container or similar
      // At minimum, the backslash commands should not be entity-encoded
      expect(result).not.toContain("___LATEX_BACKSLASH___");
    });

    it("should render block math with backslashes", () => {
      const result = renderPipeline("$$\\sum_{i=0}^{n} x_i$$");
      expect(result).not.toContain("___LATEX_BACKSLASH___");
    });

    it("should render math with comparison operators via unescapeHtmlForMath", () => {
      // The unescapeHtmlForMath helper should restore < and > for MathJax
      const unescaped = unescapeHtmlForMath("x &lt; y");
      expect(unescaped).toBe("x < y");
    });

    it("should unescape all HTML entities for math", () => {
      const input = "&lt; &gt; &amp; &apos; &quot;";
      const result = unescapeHtmlForMath(input);
      expect(result).toBe("< > & ' \"");
    });
  });

  describe("protectBackslashesInLatex only protects backslashes", () => {
    it("should protect backslashes in inline math", () => {
      const result = protectBackslashesInLatex("$\\frac{1}{2}$");
      expect(result).toContain("___LATEX_BACKSLASH___");
      expect(result).not.toContain("___LATEX_LT___");
    });

    it("should NOT protect < > & in inline math", () => {
      const result = protectBackslashesInLatex("$x < y & z > w$");
      // < > & should remain as-is (for escapeHtmlCharacters to handle)
      expect(result).toContain("<");
      expect(result).toContain(">");
      expect(result).toContain("&");
      expect(result).not.toContain("___LATEX_LT___");
      expect(result).not.toContain("___LATEX_GT___");
      expect(result).not.toContain("___LATEX_AMP___");
    });

    it("should NOT protect < > & in block math", () => {
      const result = protectBackslashesInLatex("$$x < y$$");
      expect(result).toContain("<");
      expect(result).not.toContain("___LATEX_LT___");
    });
  });

  describe("restoreBackslashesForLatex only restores backslashes", () => {
    it("should restore backslash placeholders", () => {
      const result = restoreBackslashesForLatex("___LATEX_BACKSLASH___frac");
      expect(result).toBe("\\frac");
    });

    it("should not restore HTML character placeholders (they no longer exist)", () => {
      // These placeholders should not appear in the pipeline anymore,
      // but verify the function doesn't have leftover handling
      const input = "&lt;script&gt;";
      const result = restoreBackslashesForLatex(input);
      expect(result).toBe("&lt;script&gt;");
    });
  });
});
