/**
 * Generates a GitHub commit URL based on the repository origin URL and the commit hash.
 */
export const ghCommitUrl = (origin: string, commit: string): string => {
  const baseUrl = origin
    .replace(/\.git$/, "")
    .replace(/^git@github.com:/, "https://github.com/");
  return `${baseUrl}/commit/${commit}`;
};
