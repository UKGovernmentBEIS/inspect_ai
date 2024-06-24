export const ghCommitUrl = (origin, commit) => {
  const baseUrl = origin.replace(/\.git$/, "");
  return `${baseUrl}/commit/${commit}`;
};
