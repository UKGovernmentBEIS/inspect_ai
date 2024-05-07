


// quotes values which have a space
export function shQuote(value: string): string {
  if (/\s/g.test(value)) {
    return `"${value}"`;
  } else {
    return value;
  }
}
