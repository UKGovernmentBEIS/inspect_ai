import { register } from "./Log-Reader.mjs";

export const rawFileReader = {
  name: "RawFileReader",
  canRead: () => {
    return true;
  },
  read: (contents) => {
    return JSON.parse(contents);
  },
};

register(rawFileReader);
