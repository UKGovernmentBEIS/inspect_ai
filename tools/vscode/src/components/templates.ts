
import { ExtensionContext, Uri, workspace } from "vscode";

export interface Template {
    name: string
}

export const templates = {
    "python_task": {
        name: "task.py.template"
    }
};

export const readTemplate = async (template: Template, context: ExtensionContext, variables: Record<string, string> = {}) => {
    // Compute the template path
    const extensionUri = context.extensionUri;    
    const templateUri = Uri.joinPath(extensionUri, "assets", "templates", template.name);

    // Read and decode the text file
    const templateRaw = await workspace.fs.readFile(templateUri);
    const textDecoder = new TextDecoder('utf-8');
    let templateContent = textDecoder.decode(templateRaw);

    // Replace variables
    Object.keys(variables).forEach((key) => {
        templateContent = templateContent.replaceAll(`{{<${key}>}}`, variables[key]);
    });

    return templateContent;
};