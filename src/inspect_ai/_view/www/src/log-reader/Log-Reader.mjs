const adapters = [];

export const register = (adapter) => {
  adapters.push(adapter);
};

export const readLogFile = (filename, text) => {
  const adapter = adapters.find((adapter) => {
    return adapter.canRead(filename);
  });

  // TODO Exception handling
  if (!adapter) {
    throw new Error(
      `The file ${filename} is not recognized as a valid log file`,
    );
  }
  try {
    return adapter.read(text);
  } catch (e) {
    throw new Error(
      `Failed to parse the file ${filename}. Please check the file exists and that the format is valid.\n\n${e.message}`,
    );
  }
};
