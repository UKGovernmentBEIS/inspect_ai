export const highlightNthOccurrence = (
  element: HTMLElement,
  searchTerm: string,
  occurrence: number,
): HTMLElement | null => {
  // Walk the text nodes in the element to find matches
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);

  let currentOccurrence = 0;
  let textNode: Text | null;

  while ((textNode = walker.nextNode() as Text | null)) {
    const text = textNode?.textContent;
    if (!text) continue;

    const regex = new RegExp(escapeRegex(searchTerm), "gi");
    let match: RegExpExecArray | null;

    while ((match = regex.exec(text)) !== null) {
      currentOccurrence++;

      if (currentOccurrence === occurrence) {
        // Found our target - split and wrap
        const beforeText = text.substring(0, match.index);
        const matchText = match[0];
        const afterText = text.substring(match.index + matchText.length);

        const highlight = document.createElement("mark");
        highlight.textContent = matchText;

        const parent = textNode.parentNode;
        if (!parent) return null;

        if (beforeText)
          parent.insertBefore(document.createTextNode(beforeText), textNode);
        parent.insertBefore(highlight, textNode);
        if (afterText)
          parent.insertBefore(document.createTextNode(afterText), textNode);
        parent.removeChild(textNode);

        return highlight;
      }
    }
  }
  return null;
};

const escapeRegex = (text: string): string => {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
};
