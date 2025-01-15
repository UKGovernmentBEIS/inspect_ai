# Intervention Demo

## Introduction

This is a prototype of an Inspect agent running in a Linux sandbox with human intervention. It utilises Inspect's [Interactivity features](https://inspect.ai-safety-institute.org.uk/interactivity.html). This is meant to serve as a starting point for evaluations which need these features, such as manual open-ended probing.

## Usage Modes

Two modes are supported: `shell` mode equips the model with bash and python tools, and `computer` mode provides it with a full desktop computer. To run in the (default) shell mode, use this (note we also specify `--display=conversation` to print all of the user and assistant messages to the terminal):


``` bash
inspect eval examples/intervention.py --display conversation
```

To run in computer mode, use the `mode` task parameter:

``` bash
inspect eval examples/intervention.py -T mode=computer --display conversation
```

See the documentation on the [Computer Tool](https://inspect.ai-safety-institute.org.uk/tools.html#sec-computer) for additional details on Inspect comptuer use.

## Approval

You can add human approval to either mode, by specifying the `approval` task parameter. For example:

``` bash
inspect eval examples/intervention.py -T mode=shell -T approval=true --display conversation
```

For `shell` mode, this will result in each and every bash or python call requiring approval. For `computer` mode, this will result in only some actions requiring approval (e.g. clicks require approval, but mouse moves do not). Here is the approval.yaml file used for computer mode:

```{.yaml filename="approval.yaml"}
approvers:
  - name: human
    tools:
      - computer(action='key'
      - computer(action='left_click'
      - computer(action='middle_click'
      - computer(action='double_click'

  - name: auto
    tools: "*"
```

See the [Approval](https://inspect.ai-safety-institute.org.uk/approval.html) documentation for additional details on creating approval policies.
