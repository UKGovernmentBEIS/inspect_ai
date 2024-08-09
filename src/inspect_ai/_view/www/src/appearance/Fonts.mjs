// @ts-check
/**
 * The base font size in rem units.
 * @constant {number}
 */
const kBaseFontSize = 0.9;

/**
 * Scales the base font size by the provided scale factor.
 * @param {number} scale - The scale factor to adjust the base font size.
 * @returns {string} - The scaled font size in rem units.
 */
const ScaleBaseFont = (scale) => {
  return `${kBaseFontSize + scale}rem`;
};

/**
 * @typedef {Object} FontSize
 * @property {string} title - The font size for titles.
 * @property {string} title-secondary - The font size for secondary titles.
 * @property {string} larger - The font size for larger text.
 * @property {string} large - The font size for large text.
 * @property {string} base - The base font size.
 * @property {string} small - The font size for small text.
 * @property {string} smaller - The font size for smaller text.
 */

/**
 * An object representing font sizes for different text elements.
 * @type {FontSize}
 */
export const FontSize = {
  title: ScaleBaseFont(0.6),
  "title-secondary": ScaleBaseFont(0.4),
  larger: ScaleBaseFont(0.2),
  large: ScaleBaseFont(0.1),
  base: ScaleBaseFont(0),
  small: ScaleBaseFont(-0.1),
  smaller: ScaleBaseFont(-0.1),
};

/**
 * @typedef {Object} TextStyle
 * @property {Object} label - The style for label text.
 * @property {string} label.textTransform - The text transformation for label text.
 * @property {Object} secondary - The style for secondary text.
 * @property {string} secondary.color - The color for secondary text.
 */

/**
 * An object representing text styles for different elements.
 * @type {TextStyle}
 */
export const TextStyle = {
  label: {
    textTransform: "uppercase",
  },
  secondary: {
    color: "var(--bs-secondary)",
  },
};
