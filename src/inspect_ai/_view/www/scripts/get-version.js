import { execSync } from 'child_process';

/**
 * Get version information from git describe
 * Returns an object with version and commit hash
 */
function getVersionInfo() {
  try {
    // Use git describe without --dirty since the build output itself creates dirty state
    const gitDescribe = execSync(
      "git describe --tags --long --match '[0-9]*.[0-9]*.[0-9]*'",
      { encoding: 'utf-8' }
    ).trim();

    // Extract short commit hash (first 8 chars of the hash part)
    const match = gitDescribe.match(/-g([a-f0-9]+)/);
    const commitHash = match ? match[1].substring(0, 8) : 'unknown';

    return {
      version: gitDescribe,
      commitHash: commitHash,
    };
  } catch (error) {
    console.warn('Warning: Could not get git version info:', error.message);
    return {
      version: 'unknown',
      commitHash: 'unknown',
    };
  }
}

// Export for use in vite.config.js
export default getVersionInfo;

// When run directly, print version info as JSON
if (import.meta.url === `file://${process.argv[1]}`) {
  console.log(JSON.stringify(getVersionInfo(), null, 2));
}
