// @ts-check
/**
 * Clears the current text selection in the document.
 */
export const clearDocumentSelection = () => {
  const sel = window.getSelection();
  if (sel) {
    if (sel.removeAllRanges) {
      sel.removeAllRanges();
    } else if (sel.empty) {
      sel.empty();
    }
  }
};
