/**
 * Pure DOM utility functions for cross-node text matching in FindBand search.
 * Zero React imports. Handles text nodes split across multiple DOM elements.
 */

/**
 * Build a searchable text string from a DOM subtree, tracking node boundaries.
 * Skips text nodes inside elements with data-unsearchable or user-select:none.
 * Inserts '\n' separators at unsearchable boundaries to prevent false cross-boundary matches.
 *
 * @param root The root element to search within
 * @returns Object with concatenated lowercase text, parallel arrays of nodes and their offsets
 */
export function buildSearchableText(root: Element): {
  text: string;
  nodes: Text[];
  offsets: number[];
} {
  const nodes: Text[] = [];
  const offsets: number[] = [];
  let text = "";

  // Cache for computed styles to avoid repeated getComputedStyle calls
  const styleCache = new WeakMap<Element, boolean>();

  /**
   * Check if an element or any ancestor is unsearchable.
   * Uses element.closest() for fast path, then getComputedStyle with caching.
   */
  function isUnsearchable(node: Node): boolean {
    let el: Element | null =
      node.nodeType === Node.ELEMENT_NODE
        ? (node as Element)
        : node.parentElement;

    if (!el) return false;

    // Fast path: check for data-unsearchable attribute
    if (el.closest("[data-unsearchable]")) {
      return true;
    }

    // Check ancestors for user-select: none with caching
    let current: Element | null = el;
    while (current) {
      if (styleCache.has(current)) {
        if (styleCache.get(current)) {
          return true;
        }
      } else {
        const isNone = getComputedStyle(current).userSelect === "none";
        styleCache.set(current, isNone);
        if (isNone) {
          return true;
        }
      }
      current = current.parentElement;
    }

    return false;
  }

  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let textNode: Node | null;

  while ((textNode = walker.nextNode())) {
    if (isUnsearchable(textNode)) {
      // Insert separator to prevent false matches bridging across unsearchable regions
      text += "\n";
    } else {
      // Record the offset where this node's text starts
      offsets.push(text.length);
      nodes.push(textNode as Text);

      // Append the node's text (lowercase for case-insensitive matching)
      const nodeText = textNode.textContent ?? "";
      text += nodeText.toLowerCase();
    }
  }

  return { text, nodes, offsets };
}

/**
 * Count the number of occurrences of a search term in searchable text.
 * Case-insensitive.
 *
 * @param searchableText The concatenated lowercase text from buildSearchableText
 * @param term The search term (will be lowercased)
 * @returns Number of matches found
 */
export function countMatches(searchableText: string, term: string): number {
  let count = 0;
  let pos = 0;
  const lower = term.toLowerCase();

  while ((pos = searchableText.indexOf(lower, pos)) !== -1) {
    count++;
    pos += lower.length;
  }

  return count;
}

/**
 * Find the nth occurrence (1-based) of a search term in searchable text.
 *
 * @param text The concatenated lowercase text from buildSearchableText
 * @param term The search term (will be lowercased)
 * @param n The occurrence number (1-based)
 * @returns Object with globalStart and globalEnd offsets, or null if fewer than n matches exist
 */
export function findNthMatch(
  text: string,
  term: string,
  n: number,
): { globalStart: number; globalEnd: number } | null {
  let count = 0;
  let pos = 0;
  const lower = term.toLowerCase();

  while ((pos = text.indexOf(lower, pos)) !== -1) {
    count++;
    if (count === n) {
      return {
        globalStart: pos,
        globalEnd: pos + lower.length,
      };
    }
    pos += lower.length;
  }

  return null;
}

/**
 * Map a global offset in the concatenated text to a specific text node and offset within that node.
 * Uses binary search through the offsets array.
 *
 * @param nodes Parallel array of Text nodes from buildSearchableText
 * @param offsets Parallel array of offsets from buildSearchableText
 * @param globalOffset The offset in the concatenated text
 * @returns Object with the text node and offset within that node, or null if not found
 */
export function mapOffsetToNode(
  nodes: Text[],
  offsets: number[],
  globalOffset: number,
): { node: Text; offset: number } | null {
  if (nodes.length === 0 || offsets.length === 0) {
    return null;
  }

  // Binary search to find the node containing this offset
  let left = 0;
  let right = offsets.length - 1;

  while (left <= right) {
    const mid = Math.floor((left + right) / 2);
    const nodeStart = offsets[mid];
    const nodeEnd = mid + 1 < offsets.length ? offsets[mid + 1] : Infinity;

    if (globalOffset >= nodeStart && globalOffset < nodeEnd) {
      return {
        node: nodes[mid],
        offset: globalOffset - nodeStart,
      };
    }

    if (globalOffset < nodeStart) {
      right = mid - 1;
    } else {
      left = mid + 1;
    }
  }

  return null;
}

/**
 * Create a Range and StaticRange for a match spanning potentially multiple text nodes.
 * Validates that the range is connected and not collapsed.
 *
 * @param nodes Parallel array of Text nodes from buildSearchableText
 * @param offsets Parallel array of offsets from buildSearchableText
 * @param match Object with globalStart and globalEnd from findNthMatch
 * @returns Object with both Range and StaticRange, or null if range is invalid
 */
export function createMatchRange(
  nodes: Text[],
  offsets: number[],
  match: { globalStart: number; globalEnd: number },
): { range: Range; staticRange: StaticRange } | null {
  const startMapping = mapOffsetToNode(nodes, offsets, match.globalStart);
  const endMapping = mapOffsetToNode(nodes, offsets, match.globalEnd);

  if (!startMapping || !endMapping) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn(
        "createMatchRange: Could not map match offsets to nodes",
        match,
      );
    }
    return null;
  }

  const range = document.createRange();
  range.setStart(startMapping.node, startMapping.offset);
  range.setEnd(endMapping.node, endMapping.offset);

  // Validate the range
  if (
    range.collapsed ||
    !range.startContainer.isConnected ||
    !range.endContainer.isConnected
  ) {
    if (typeof console !== "undefined" && console.warn) {
      console.warn(
        "createMatchRange: Range is collapsed or disconnected",
        range,
      );
    }
    return null;
  }

  const staticRange = new StaticRange({
    startContainer: startMapping.node,
    startOffset: startMapping.offset,
    endContainer: endMapping.node,
    endOffset: endMapping.offset,
  });

  return { range, staticRange };
}
