import { ConfigurationTarget, workspace } from "vscode";


export interface EditorAssociation {
  viewType: string;
  filenamePattern: string;
}


export async function withEditorAssociation(
  association: EditorAssociation,
  fn: () => Promise<void>) {

  // get existing associations
  const kEditorAssociations = 'editorAssociations';
  const config = workspace.getConfiguration('workbench');
  const configuredAssociations: Record<string, string> | undefined = config.get(kEditorAssociations);
  const existingAssociations = (configuredAssociations && Object.keys(configuredAssociations).length > 0)
    ? configuredAssociations
    : undefined;


  // temporarily update
  const updatedAssociations: Record<string, string> = {
    ...existingAssociations,
    [association.filenamePattern]: association.viewType
  };
  await config.update(kEditorAssociations, updatedAssociations, ConfigurationTarget.Workspace);

  // execute and unwind update
  try {
    await fn();
  } finally {
    await config.update(kEditorAssociations, existingAssociations, ConfigurationTarget.Workspace);
  }

}
