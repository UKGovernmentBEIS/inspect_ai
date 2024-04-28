import { register } from "./Log-Reader.mjs";

export const rawFileReader = {
  name: "RawFileReader",
  canRead: (_filename) => {
    return true;
  },
  read: (contents) => {
    return JSON.parse(contents);
  },
};

register(rawFileReader);
