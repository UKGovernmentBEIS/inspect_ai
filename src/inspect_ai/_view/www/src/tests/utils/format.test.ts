import {
  arrayToString,
  formatTime,
  formatPrettyDecimal,
  formatDecimalNoTrailingZeroes,
  toTitleCase,
  formatNoDecimal,
  formatDuration,
} from "../../utils/format";

describe("arrayToString", () => {
  test("converts array to comma-separated string", () => {
    expect(arrayToString(["one", "two", "three"])).toBe("one, two, three");
  });

  test("handles single string input", () => {
    expect(arrayToString("single")).toBe("single");
  });

  test("handles empty array", () => {
    expect(arrayToString([])).toBe("");
  });
});

describe("formatTime", () => {
  test("formats seconds when less than a minute", () => {
    expect(formatTime(45)).toBe("45.0 sec");
  });

  test("formats minutes and seconds", () => {
    expect(formatTime(125)).toBe("2 min 5 sec");
  });

  test("formats hours, minutes, and seconds", () => {
    expect(formatTime(3665)).toBe("1 hr 1 min 5 sec");
  });

  test("formats days, hours, minutes, and seconds", () => {
    expect(formatTime(90061)).toBe("1 days 1 hr 1 min 1 sec");
  });
});

describe("formatPrettyDecimal", () => {
  test("adds one decimal place to whole numbers", () => {
    expect(formatPrettyDecimal(5)).toBe("5.0");
  });

  test("keeps decimal places if less than maxDecimals", () => {
    expect(formatPrettyDecimal(5.12, 3)).toBe("5.12");
  });

  test("truncates decimal places if more than maxDecimals", () => {
    expect(formatPrettyDecimal(5.12345, 2)).toBe("5.12");
  });

  test("uses default maxDecimals if not provided", () => {
    expect(formatPrettyDecimal(5.12345)).toBe("5.123");
  });
});

describe("formatDecimalNoTrailingZeroes", () => {
  test("removes trailing zeroes from decimal", () => {
    expect(formatDecimalNoTrailingZeroes(5.1)).toBe("5.1");
  });

  test("keeps whole numbers as is", () => {
    expect(formatDecimalNoTrailingZeroes(5)).toBe("5");
  });

  test("handles non-numbers (should be fixed later)", () => {
    const nonNumber = "test" as unknown as number;
    expect(formatDecimalNoTrailingZeroes(nonNumber)).toBe(nonNumber);
  });
});

describe("toTitleCase", () => {
  test("converts string to title case", () => {
    expect(toTitleCase("hello world")).toBe("Hello World");
  });

  test("handles uppercase strings", () => {
    expect(toTitleCase("HELLO WORLD")).toBe("Hello World");
  });

  test("handles mixed case strings", () => {
    expect(toTitleCase("hElLo WoRlD")).toBe("Hello World");
  });

  test("handles empty string", () => {
    expect(toTitleCase("")).toBe("");
  });
});

describe("formatNoDecimal", () => {
  test("rounds number to whole number", () => {
    expect(formatNoDecimal(5.6)).toBe("6");
  });

  test("handles integer values", () => {
    expect(formatNoDecimal(5)).toBe("5");
  });

  test("handles non-numbers (should be fixed later)", () => {
    const nonNumber = "test" as unknown as number;
    expect(formatNoDecimal(nonNumber)).toBe(nonNumber);
  });
});

describe("formatDuration", () => {
  test("formats duration between two dates", () => {
    const start = new Date("2023-01-01T00:00:00Z");
    const end = new Date("2023-01-01T00:01:30Z");
    expect(formatDuration(start, end)).toBe("1 min 30 sec");
  });

  test("handles short durations", () => {
    const start = new Date("2023-01-01T00:00:00Z");
    const end = new Date("2023-01-01T00:00:10Z");
    expect(formatDuration(start, end)).toBe("10.0 sec");
  });

  test("handles long durations", () => {
    const start = new Date("2023-01-01T00:00:00Z");
    const end = new Date("2023-01-02T01:01:01Z");
    expect(formatDuration(start, end)).toBe("1 days 1 hr 1 min 1 sec");
  });
});
