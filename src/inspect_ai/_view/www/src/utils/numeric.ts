export function compareWithNan(a: number, b: number): number {
  const aIsNaN = Number.isNaN(a);
  const bIsNaN = Number.isNaN(b);

  if (aIsNaN && bIsNaN) {
    return 0;
  }

  if (aIsNaN) {
    return 1;
  }
  if (bIsNaN) {
    return -1;
  }

  return a - b;
}
