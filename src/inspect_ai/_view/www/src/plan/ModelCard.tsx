import { FC } from "react";
import { ApplicationIcons } from "../appearance/icons";
import { Card, CardBody, CardHeader } from "../components/Card";
import { EvalModelConfig, EvalSpec } from "../types/log";

import clsx from "clsx";
import { MetaDataGrid } from "../metadata/MetaDataGrid";
import styles from "./ModelCard.module.css";

interface ModelCardProps {
  evalSpec?: EvalSpec;
}

/**
 * Renders the plan card
 */
export const ModelCard: FC<ModelCardProps> = ({ evalSpec }) => {
  if (!evalSpec) {
    return undefined;
  }

  const modelsInfo: Record<string, EvalModelConfig> = {
    eval: {
      model: evalSpec.model,
      base_url: evalSpec.model_base_url,
      config: evalSpec.model_generate_config,
      args: evalSpec.model_args,
    },
    ...evalSpec.model_roles,
  };

  const noneEl = <span className="text-style-secondary">None</span>;

  return (
    <Card>
      <CardHeader icon={ApplicationIcons.model} label="Models" />
      <CardBody id={"task-model-card-body"}>
        <div className={styles.container}>
          {Object.keys(modelsInfo || {}).map((modelKey) => {
            const modelInfo = modelsInfo[modelKey];
            return (
              <div
                key={modelKey}
                className={clsx(styles.modelInfo, "text-size-small")}
              >
                <div
                  className={clsx(
                    styles.role,
                    "text-style-label",
                    "text-style-secondary",
                  )}
                >
                  {modelKey}
                </div>

                <div className={clsx("text-style-label")}>Model</div>
                <div>{modelInfo.model}</div>

                <div className={clsx("text-style-label")}>Base Url</div>
                <div className="text-size-small">
                  {modelInfo.base_url || noneEl}
                </div>
                <div className={clsx("text-style-label")}>Configuration</div>
                <div className="text-size-small">
                  {Object.keys(modelInfo.config).length > 0 ? (
                    <MetaDataGrid
                      entries={
                        modelInfo.config as any as Record<string, unknown>
                      }
                    />
                  ) : (
                    noneEl
                  )}
                </div>
                <div className={clsx("text-style-label")}>Args</div>
                <div className="text-size-small">
                  {Object.keys(modelInfo.args).length > 0 ? (
                    <MetaDataGrid
                      entries={modelInfo.args as any as Record<string, unknown>}
                    />
                  ) : (
                    noneEl
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </CardBody>
    </Card>
  );
};
