import { TextEncoder, TextDecoder } from "util";

import { clearLargeEventsArray } from "../../utils/clear-events-preprocessor";

const encoder = new TextEncoder();
const decoder = new TextDecoder() as InstanceType<
  typeof globalThis.TextDecoder
>;

function encode(str: string): Uint8Array {
  return encoder.encode(str);
}

function decode(data: Uint8Array): string {
  return decoder.decode(data);
}

describe("clearLargeEventsArray", () => {
  it("returns data unchanged when total size is under the limit", () => {
    const json = '{"events": [1,2,3], "other": "data"}';
    const data = encode(json);
    const result = clearLargeEventsArray(data);
    expect(decode(result)).toBe(json);
  });

  it("returns data unchanged for small payloads even with events", () => {
    const json = '{"id":"test","events":[{"event":"model"}],"scores":{}}';
    const data = encode(json);
    const result = clearLargeEventsArray(data);
    expect(decode(result)).toBe(json);
  });

  it("preserves valid JSON structure when events are at different positions", () => {
    // Events as last property
    const json1 = '{"id":"test","scores":{},"events":[1,2,3]}';
    const data1 = encode(json1);
    expect(decode(clearLargeEventsArray(data1))).toBe(json1);

    // Events as first property
    const json2 = '{"events":[1,2,3],"id":"test"}';
    const data2 = encode(json2);
    expect(decode(clearLargeEventsArray(data2))).toBe(json2);

    // Events as middle property
    const json3 = '{"id":"test","events":[1,2,3],"scores":{}}';
    const data3 = encode(json3);
    expect(decode(clearLargeEventsArray(data3))).toBe(json3);
  });

  it("handles JSON with no events property", () => {
    const json = '{"id":"test","scores":{}}';
    const data = encode(json);
    expect(decode(clearLargeEventsArray(data))).toBe(json);
  });
});
