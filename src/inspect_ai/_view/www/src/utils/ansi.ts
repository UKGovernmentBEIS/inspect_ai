/**
 * Detects if text contains ANSI escape sequences.
 *
 * This function checks for various ANSI escape codes including:
 * - CSI (Control Sequence Introducer) sequences: ESC [ ... (colors, cursor movement, etc.)
 * - OSC (Operating System Command) sequences: ESC ] ... (terminal titles, hyperlinks)
 * - Simple escape sequences: ESC followed by a single character
 *
 * @param text - The text to check for ANSI escape sequences
 * @returns true if ANSI escape sequences are detected, false otherwise
 */
export const isAnsiOutput = (text: string): boolean => {
  // Comprehensive ANSI escape sequence regex
  // Matches:
  // 1. CSI sequences: ESC [ <params> <command>
  //    Examples: \x1b[0m (reset), \x1b[31m (red), \x1b[2J (clear screen)
  // 2. OSC sequences: ESC ] <params> BEL or ESC ] <params> ESC \
  //    Examples: \x1b]0;Title\x07 (set title), \x1b]8;;url\x07 (hyperlink)
  // 3. Simple escape sequences: ESC <letter>
  //    Examples: \x1bM (reverse index), \x1b7 (save cursor)
  const ansiRegex =
    // eslint-disable-next-line no-control-regex
    /\x1b(?:\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]|\].*?(?:\x07|\x1b\\)|[^[\]>])/g;

  return ansiRegex.test(text);
};
