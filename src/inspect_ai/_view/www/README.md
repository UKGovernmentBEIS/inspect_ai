The Inspect log viewer is now built into a bundled js file using `vite`, but it is important that users who clone or install from the repo directly are able to run the viewer without needing an explicit build step. To support this, we keep a bundled version of the viewer committed into the repo in the `dist` folder. **When you make changes, your commits/PRs must include updates to the bundled files in the `dist` folder as well as the source code changes.** 


## Before You Commit:

Use the following commands (run in the `src/inspect_ai/_view/www` dir) to ensure your commits are ready to go:

1. Run eslint to catch any linting errors:

   ```bash
   yarn eslint .
   ```

   Fix any errors reported.

2. Run prettier to ensure formatting:

   ```bash
   yarn prettier:write
   ```

3. Build the bundled output to `dist`

   ```bash
   yarn build
   ```
   
   Don't forget to stage newly updated changes in the `dist` folder.