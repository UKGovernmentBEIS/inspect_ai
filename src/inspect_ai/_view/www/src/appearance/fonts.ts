/**
 * The base font size in rem units.
 */
const kBaseFontSize: number = 0.9;

/**
 * Scales the base font size by the provided scale factor.
 */
const ScaleBaseFont = (scale: number): string => {
  return `${kBaseFontSize + scale}rem`;
};

/**
 * An object representing font sizes for different text elements.
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
 * An object representing text styles for different elements.
 */
export const TextStyle = {
  label: {
    textTransform: "uppercase",
  },
  secondary: {
    color: "var(--bs-secondary)",
  },
  tertiary: {
    color: "var(--bs-tertiary-color)",
  },
};
