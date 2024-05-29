import { ConfigurationTarget, workspace } from "vscode";

const kPackageIndexDepthsSetting = "packageIndexDepths";

export const initializeGlobalSettings = async () => {
    const pythonAnalysis = workspace.getConfiguration("python.analysis") || [];
    const pkgIndexDepths =
        pythonAnalysis.get<Array<{ name: string; depth: number }>>(
            kPackageIndexDepthsSetting
        ) || [];

    try {
        kInspectPackageIndexDepth.forEach((pkgDep) => {
            if (
                !pkgIndexDepths.find((p) => {
                    return pkgDep.name === p.name;
                })
            ) {
                pkgIndexDepths.push(pkgDep);
            }
        });
        await pythonAnalysis.update(
            kPackageIndexDepthsSetting,
            pkgIndexDepths,
            ConfigurationTarget.Global
        );
    } catch {
        // This can happen if the user disables the Pylance extension
        // in that case, since this is a Pylance setting, we're safe to just
        // ignore it
        // 
        // Don't log since this is an allowed state (we don't require Pylance)
        // and continue for any exception since we shouldn't allow this setting
        // to block extension init
    }

    const config = workspace.getConfiguration("editor", { languageId: "json" });
    await config.update("wordWrap", "on", true);
};

const kInspectPackageIndexDepth = [
    {
        name: "inspect_ai",
        depth: 2,
    },
];
