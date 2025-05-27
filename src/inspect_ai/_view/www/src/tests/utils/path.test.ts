import { dirname, filename } from "../../utils/path";

describe("filename", () => {
  test("extracts filename without extension from a path", () => {
    expect(filename("/path/to/file.txt")).toBe("file");
    expect(filename("file.txt")).toBe("file");
    expect(filename("/path/to/document.pdf")).toBe("document");
  });

  test("handles paths without extensions", () => {
    expect(filename("/path/to/file")).toBe("/path/to/file");
    expect(filename("file")).toBe("file");
  });

  test("handles paths with multiple dots", () => {
    expect(filename("/path/to/file.name.txt")).toBe("file.name");
    expect(filename("archive.tar.gz")).toBe("archive.tar");
  });

  test("handles edge cases", () => {
    expect(filename("")).toBe("");
    expect(filename(".")).toBe(".");
    // Special case for .hidden files - there's no extension to remove
    expect(filename(".hidden")).toBe(".hidden");
    // Dot files with extensions should have the extension removed
    expect(filename(".hidden.txt")).toBe(".hidden");
  });
});

describe("dirname", () => {
  test("extracts directory name from a path", () => {
    expect(dirname("/path/to/file.txt")).toBe("/path/to");
    expect(dirname("/path/to/directory/")).toBe("/path/to");
    expect(dirname("/path/to/file")).toBe("/path/to");
  });

  test("handles paths without directories", () => {
    expect(dirname("file.txt")).toBe("");
    expect(dirname("file")).toBe("");
  });

  test("handles root directory", () => {
    expect(dirname("/file.txt")).toBe("");
    expect(dirname("/file")).toBe("");
  });

  test("handles empty input", () => {
    expect(dirname("")).toBe("");
  });

  test("handles paths with trailing slash", () => {
    expect(dirname("/path/to/directory/")).toBe("/path/to");
  });
});
