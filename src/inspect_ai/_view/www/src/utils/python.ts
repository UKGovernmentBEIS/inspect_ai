/**
 * Extracts the package and module names from a fully qualified Python module path
 *
 * @param name - A Python import path that may include a package name
 * @returns An object containing the package and module names
 */
export const parsePackageName = (name: string): PythonName => {
  if (name.includes("/")) {
    const [packageName, moduleName] = name.split("/", 2);
    return { package: packageName, module: moduleName };
  }
  return { package: "", module: name };
};

export interface PythonName {
  package: string;
  module: string;
}
