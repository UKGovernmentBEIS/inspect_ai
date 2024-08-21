// @ts-check
/**
 * Generates a GitHub commit URL based on the repository origin URL and the commit hash.
 *
 * @param {string} origin - The origin URL of the GitHub repository.
 * @param {string} commit - The commit hash.
 * @returns {string} - The generated GitHub commit URL.
 */
export const ghCommitUrl = (origin, commit) => {
  const baseUrl = origin.replace(/\.git$/, "");
  return `${baseUrl}/commit/${commit}`;
};
