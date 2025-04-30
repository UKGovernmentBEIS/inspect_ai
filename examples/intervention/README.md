# Intervention Demo

## Introduction

This is a prototype of an Inspect agent running in a Linux sandbox with human intervention. It utilises Inspect's [Interactivity features](https://inspect.aisi.org.uk/interactivity.html). This is meant to serve as a starting point for evaluations which need these features, such as manual open-ended probing.

## Usage Modes

Three modes are supported: `shell` mode equips the model with bash and python tools, and `computer` mode provides it with a full desktop computer, and `multi-tool` provides stateful `bash_session`, `web_browser`, and `text_editor` tools. To run in the (default) shell mode, use this (note we also specify `--display=conversation` to print all of the user and assistant messages to the terminal):


``` bash
inspect eval examples/intervention --display conversation
```

To run in computer or multi-tool modes, use the `mode` task parameter:

``` bash
inspect eval examples/intervention -T mode=computer --display conversation
inspect eval examples/intervention -T mode=multi-tool --display conversation
```

See the documentation on the [Computer Tool](https://inspect.aisi.org.uk/tools-standard.html#sec-computer) for additional details on Inspect computer use.

## Approval

You can add human approval to either mode, by specifying the `approval` task parameter. For example:

``` bash
inspect eval examples/intervention -T mode=shell -T approval=true --display conversation
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

See the [Approval](https://inspect.aisi.org.uk/approval.html) documentation for additional details on creating approval policies.
