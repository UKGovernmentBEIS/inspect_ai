# Inspect Extensions

## Sandboxes

- **[Daytona Sandbox](https://meridianlabs-ai.github.io/inspect_sandboxes/daytona.html)** — [Meridian](https://github.com/meridianlabs-ai/inspect_sandboxes)
  Sandbox environment for Inspect using Daytona's cloud infrastructure.
- **[EC2 Sandbox](https://github.com/UKGovernmentBEIS/inspect_ec2_sandbox)** — [UK AISI](https://github.com/UKGovernmentBEIS/inspect_ec2_sandbox)
  Python package that provides a EC2 virtual machine sandbox environment for Inspect.
- **[k8s Sandbox](https://k8s-sandbox.aisi.org.uk/)** — [UK AISI](https://github.com/UKGovernmentBEIS/inspect_k8s_sandbox)
  Python package that provides a Kubernetes sandbox environment for Inspect.
- **[Modal Sandbox](https://meridianlabs-ai.github.io/inspect_sandboxes/modal.html)** — [Meridian](https://github.com/meridianlabs-ai/inspect_sandboxes)
  Serverless container sandbox for Inspect using Modal's cloud infrastructure.
- **[Podman Sandbox](https://github.com/VectorInstitute/inspect-podman)** — [Vector Institute](https://github.com/VectorInstitute/inspect-podman)
  Podman-backed sandbox environment for Inspect, enabling containerized tool calls without Docker.
- **[Policy Sandbox](https://github.com/Dedulus/inspect-policy-sandbox)** — [Arnab Mitra](https://github.com/Dedulus)
  Sandbox wrapper that allows fine grained control over command execution and file I/O.
- **[Proxmox Sandbox](https://github.com/UKGovernmentBEIS/inspect_proxmox_sandbox)** — [UK AISI](https://github.com/UKGovernmentBEIS/inspect_proxmox_sandbox)
  Use virtual machines, running within a Proxmox instance, as Inspect sandboxes.
- **[Vagrant Sandbox](https://github.com/jasongwartz/inspect_vagrant_sandbox)** — [Jason Gwartz](https://github.com/jasongwartz)
  Use any virtual machine hypervisor supported by Hashicorp Vagrant as Inspect sandboxes.

## Analysis

- **[CJE](https://github.com/cimo-labs/cje)** — [CIMO Labs](https://cimolabs.com)
  Calibrated judge evaluation — calibrate model-graded scorer accuracy using causal inference with optional oracle labels.
- **[Docent](https://docs.transluce.org/)** — [Transluce](https://transluce.org/introducing-docent)
  Tools to summarize, cluster, and search over agent transcripts.
- **[Inspect Claim Support](https://github.com/avalyset/inspect-claim-support)** — [Eirik Botten Nicolaysen](https://github.com/avalyset)
  Faithfulness / claim-support scorer — checks whether a claimed answer is substantiated by the transcript. Absence of evidence is not treated as support.
- **[Inspect falsify](https://github.com/studio-11-co/falsify-inspect)** — [Cüneyt Öztürk](https://falsify.dev)
  Pre-register an evaluation's success criteria (metric, threshold, dataset hash, seed) as a tamper-evident PRML manifest before the run, then verify eval logs against the locked claim via installed hooks.
- **[Inspect Judge Drift](https://github.com/avalyset/inspect-judge-drift)** — [Eirik Botten Nicolaysen](https://github.com/avalyset)
  Judge-drift measurement — re-grades a stored eval log with two graders over the same samples, so the judge model is the only variable. Grade-parse failures are reported as unscored, never fabricated into verdicts.
- **[Inspect MLflow](https://github.com/debu-sinha/inspect-mlflow)** — [Debu Sinha](https://github.com/debu-sinha)
  Experiment tracking, execution tracing, LLM provider autolog, and artifact logging for Inspect AI evaluations.
- **[Inspect Scout](https://meridianlabs-ai.github.io/inspect_scout/)** — [Meridian](https://github.com/meridianlabs-ai/inspect_scout)
  Transcript analysis for Inspect evaluations.
- **[Inspect Viz](https://meridianlabs-ai.github.io/inspect_viz/)** — [Meridian](https://github.com/meridianlabs-ai/inspect_viz)
  Interactive data visualization for Inspect evaluations.
- **[Inspect WandB](https://github.com/DanielPolatajko/inspect_wandb)** — [Arcadia](https://www.arcadiaimpact.org/)
  Integration with Weights and Biases platform.

## Frameworks

- **[Control Arena](https://control-arena.aisi.org.uk)** — [UK AISI](https://github.com/UKGovernmentBEIS/control-arena)
  Framework for running experiments on AI Control and Monitoring.
- **[EvalPort](https://github.com/adhabnr-ux/evalport)** — [Sahi Katukojula](https://github.com/adhabnr-ux)
  Open standard for portable LLM evaluation datasets. Convert between Inspect AI and other eval frameworks (DeepEval, Promptfoo, LangSmith, etc.) using a portable JSON format.
- **[Inspect Cyber](https://ukgovernmentbeis.github.io/inspect_cyber/)** — [UK AISI](https://github.com/UKGovernmentBEIS/inspect_cyber)
  Python package that streamlines the process of creating agentic cyber evaluations in Inspect.
- **[Inspect Petri](https://meridianlabs-ai.github.io/inspect_petri/)** — [Meridian](https://github.com/meridianlabs-ai/inspect_petri)
  Framework for testing alignment hypotheses end‑to‑end, including automatic scenario generation.
- **[Inspect SWE](https://meridianlabs-ai.github.io/inspect_swe/)** — [Meridian](https://github.com/meridianlabs-ai/inspect_swe)
  Software engineering agents (Claude Code and Codex CLI) for Inspect.
- **[Linux Arena](https://www.linuxarena.ai)** — [Redwood Research](https://github.com/linuxarena/control-tower)
  Framework for running experiments on AI Control and Monitoring.
- **[Petri Bloom](https://meridianlabs-ai.github.io/petri_bloom/)** — [Meridian](https://github.com/meridianlabs-ai/petri_bloom)
  Framework for generating multi-turn behavioral evaluations of frontier AI models.

## Tooling

- **[Evaljobs](https://github.com/dvsrepo/evaljobs)** — [Hugging Face](https://github.com/dvsrepo/evaljobs)
  Run evals on Hugging Face GPUs and share results and code on the Hugging Face Hub.
- **[Inspect Costs Plugin](https://github.com/jasongwartz/inspect_costs_plugin/)** — [Jason Gwartz](https://github.com/jasongwartz)
  Automatically load pricing data for models under test.
- **[Inspect Flow](https://meridianlabs-ai.github.io/inspect_flow/)** — [Meridian](https://github.com/meridianlabs-ai/inspect_flow)
  Workflow orchestration for reproducibly running evals at scale.
- **[Inspect Hawk](https://hawk.metr.org)** — [METR](https://github.com/METR/hawk)
  Platform for running Inspect AI evaluations on cloud infrastructure.
- **[Inspect VS Code](https://marketplace.visualstudio.com/items?itemName=ukaisi.inspect-ai)** — [Meridian](https://github.com/meridianlabs-ai/inspect-vscode)
  VS Code extension that assists with developing and debugging Inspect evaluations.
- **[Optstop](https://github.com/UKGovernmentBEIS/optstop)** — [UK AISI](https://github.com/UKGovernmentBEIS/optstop)
  Adaptive optimal stopping algorithms to help efficiently determine when enough data has been collected to make reliable inferences.
