import { isBase64 } from "../../utils/base64";

describe("isBase64", () => {
  test("identifies valid base64 strings", () => {
    expect(isBase64("SGVsbG8gV29ybGQ=")).toBe(true); // "Hello World" in base64
    expect(isBase64("dGVzdA==")).toBe(true); // "test" in base64
    expect(isBase64("YWJjMTIzIT8kKiYoKSctPUB+")).toBe(true); // "abc123!?$*&()'-=@+" in base64
  });

  test("identifies invalid base64 strings", () => {
    expect(isBase64("not-base64")).toBe(false);
    expect(isBase64("SGVs bG8=")).toBe(false); // Contains space
    expect(isBase64("Hello World")).toBe(false);
    expect(isBase64("123")).toBe(false); // Too short for valid base64
  });

  test("handles edge cases", () => {
    expect(isBase64("")).toBe(true); // Empty string is technically valid base64
    expect(isBase64("YQ==")).toBe(true); // Single character 'a'
    expect(isBase64("YWI=")).toBe(true); // Two characters 'ab'
    expect(isBase64("YWJj")).toBe(true); // Three characters 'abc'
  });
});
