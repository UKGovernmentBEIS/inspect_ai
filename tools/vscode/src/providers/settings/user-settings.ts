import { ConfigurationTarget, workspace } from "vscode";

const kPackageIndexDepthsSetting = "packageIndexDepths";

export const initializeGlobalSettings = async () => {
    const pythonAnalysis = workspace.getConfiguration('python.analysis') || [];
    const pkgIndexDepths = pythonAnalysis.get<Array<{ name: string, depth: number }>>(kPackageIndexDepthsSetting) || [];

    kInspectPackageIndexDepth.forEach((pkgDep) => {
        if (!pkgIndexDepths.find((p) => {
            return pkgDep.name === p.name;
        })) {
            pkgIndexDepths.push(pkgDep);
        }
    });
    await pythonAnalysis.update(kPackageIndexDepthsSetting, pkgIndexDepths, ConfigurationTarget.Global);

    const config = workspace.getConfiguration('editor', { languageId: 'json' });
    await config.update('wordWrap', 'on', true);
};

const kInspectPackageIndexDepth = [
    {
        "name": "inspect_ai",
        "depth": 2
    },

];