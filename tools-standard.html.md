# Standard Tools


## Overview

Inspect has several standard tools built-in, including:

- [Bash and Python](tools-standard.qmd#sec-bash-and-python) for
  executing arbitrary shell and Python code.

- [Web Browser](tools-standard.qmd#sec-web-browser), which provides the
  model with a headless Chromium web browser that supports navigation,
  history, and mouse/keyboard interactions.

- [Computer](tools-standard.qmd#sec-computer), which provides the model
  with a desktop computer (viewed through screenshots) that supports
  mouse and keyboard interaction.

- [Web Search](tools-standard.qmd#sec-web-search), which uses the Google
  Search API to execute and summarise web searches.

## Bash and Python

The `bash()` and `python()` tools enable execution of arbitrary shell
commands and Python code, respectively. These tools require the use of a
[Sandbox Environment](sandboxing.qmd) for the execution of untrusted
code. For example, here is how you might use them in an evaluation where
the model is asked to write code in order to solve capture the flag
(CTF) challenges:

``` python
from inspect_ai.tool import bash, python

CMD_TIMEOUT = 180

@task
def intercode_ctf():
    return Task(
        dataset=read_dataset(),
        solver=[
            system_message("system.txt"),
            use_tools([
                bash(CMD_TIMEOUT), 
                python(CMD_TIMEOUT)
            ]),
            generate(),
        ],
        scorer=includes(),
        message_limit=30,
        sandbox="docker",
    )
```

We specify a 3-minute timeout for execution of the bash and python tools
to ensure that they don’t perform extremely long running operations.

See the [Agents](#sec-agents) section for more details on how to build
evaluations that allow models to take arbitrary actions over a longer
time horizon.

## Web Browser

The web browser tools provides models with the ability to browse the web
using a headless Chromium browser. Navigation, history, and
mouse/keyboard interactions are all supported.

### Configuration

Under the hood, the web browser is an instance of
[Chromium](https://www.chromium.org/chromium-projects/) orchestrated by
[Playwright](https://playwright.dev/), and runs in its own dedicated
Docker container. Therefore, to use the web_browser tool you should
reference the `aisiuk/inspect-web-browser-tool` Docker image in your
`compose.yaml`. For example, here we use it as our default image:

**compose.yaml**

``` yaml
services:
  default:
    image: aisiuk/inspect-web-browser-tool
    init: true
```

Here, we add a dedicated `web_browser` service:

**compose.yaml**

``` yaml
services:
  default:
    image: "python:3.12-bookworm"
    init: true
    command: "tail -f /dev/null"
  web_browser:
    image: aisiuk/inspect-web-browser-tool
    init: true
```

Rather than using the `aisiuk/inspect-web-browser-tool` image, you can
also just include the web browser service components in a custom image
(see [Custom Images](#sec-custom-images) below for details).

### Task Setup

A task configured to use the web browser tools might look like this:

``` python
from inspect_ai import Task, task
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import bash, python, web_browser

@task
def browser_task():
    return Task(
        dataset=read_dataset(),
        solver=[
            use_tools([bash(), python()] + web_browser()),
            generate(),
        ],
        scorer=match(),
        sandbox=("docker", "compose.yaml"),
    )
```

Note that unlike some other tool functions like `bash()`, the
`web_browser()` function returns a list of tools. Therefore, we
concatenate it with a list of the other tools we are using in the call
to `use_tools()`.

### Browsing

If you review the transcripts of a sample with access to the web browser
tool, you’ll notice that there are several distinct tools made available
for control of the web browser. These tools include:

| Tool | Description |
|----|----|
| `web_browser_go(url)` | Navigate the web browser to a URL. |
| `web_browser_click(element_id)` | Click an element on the page currently displayed by the web browser. |
| `web_browser_type(element_id)` | Type text into an input on a web browser page. |
| `web_browser_type_submit(element_id, text)` | Type text into a form input on a web browser page and press ENTER to submit the form. |
| `web_browser_scroll(direction)` | Scroll the web browser up or down by one page. |
| `web_browser_forward()` | Navigate the web browser forward in the browser history. |
| `web_browser_back()` | Navigate the web browser back in the browser history. |
| `web_browser_refresh()` | Refresh the current page of the web browser. |

The return value of each of these tools is a [web accessibility
tree](https://web.dev/articles/the-accessibility-tree) for the page,
which provides a clean view of the content, links, and form fields
available on the page (you can look at the accessibility tree for any
web page using [Chrome Developer
Tools](https://developer.chrome.com/blog/full-accessibility-tree)).

### Disabling Interactions

You can use the web browser tools with page interactions disabled by
specifying `interactive=False`, for example:

``` python
use_tools(web_browser(interactive=False))
```

In this mode, the interactive tools (`web_browser_click()`,
`web_browser_type()`, and `web_browser_type_submit()`) are not made
available to the model.

### Custom Images

Above we demonstrated how to use the pre-configured Inspect web browser
container. If you prefer to incorporate the headless web browser and its
dependencies into another container that is also supported.

To do this, reference the
[Dockerfile](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/tool/_tools/_web_browser/_resources/Dockerfile)
used in the built-in web browser container and ensure that the
dependencies, application files, and server run command it uses are also
in your container definition:

``` dockerfile
# Install playwright
RUN pip install playwright 
RUN playwright install
RUN playwright install-deps 

# Install other dependencies
RUN pip install dm-env-rpc pillow bs4 lxml

# Copy Python files alongside the Dockerfile
COPY *.py ./

# Run the server
CMD ["python3", "/app/web_browser/web_server.py"]
```

Note that all of the Python files in the
[\_resources](https://github.com/UKGovernmentBEIS/inspect_ai/blob/main/src/inspect_ai/tool/_tools/_web_browser/_resources/)
directory alongside the `Dockerfile` need to be available for copying
when building the container.

## Computer

The `computer()` tool provides models with a computer desktop
environment along with the ability to view the screen and perform mouse
and keyboard gestures. The computer tool is based on the Anthropic
[Computer Use
Beta](https://docs.anthropic.com/en/docs/build-with-claude/computer-use)
reference implementation and works with any model that supports image
input.

### Configuration

The `computer()` tool runs within a Docker container. To use it with a
task you need to reference the `aisiuk/inspect-computer-tool:latest`
image in your Docker compose file. For example:

**compose.yaml**

``` yaml
services:
  default:
    image: aisiuk/inspect-computer-tool:latest
```

You can configure the container to not have Internet access as follows:

**compose.yaml**

``` yaml
services:
  default:
    image: aisiuk/inspect-computer-tool:latest
    network_mode: none
```

Note that if you’d like to be able to view the model’s interactions with
the computer desktop in realtime, you will need to also do some port
mapping to enable a VNC connection with the container. See the [VNC
Client](#vnc-client) section below for details on how to do this.

The `aisiuk/inspect-computer-tool:latest` image is based on the
[ubuntu:22.04](https://hub.docker.com/layers/library/ubuntu/22.04/images/sha256-965fbcae990b0467ed5657caceaec165018ef44a4d2d46c7cdea80a9dff0d1ea?context=explore)
image and includes the following additional applications pre-installed:

- Firefox
- VS Code
- Xpdf
- Xpaint
- galculator

### Task Setup

A task configured to use the computer tool might look like this:

``` python
from inspect_ai import Task, task
from inspect_ai.scorer import match
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import computer

@task
def computer_task():
    return Task(
        dataset=read_dataset(),
        solver=[
            use_tools([computer()]),
            generate(),
        ],
        scorer=match(),
        sandbox=("docker", "compose.yaml"),
    )
```

#### Options

The computer tool supports the following options:

| Option | Description |
|----|----|
| `max_screenshots` | The maximum number of screenshots to play back to the model as input. Defaults to 1 (set to `None` to have no limit). |
| `timeout` | Timeout in seconds for computer tool actions. Defaults to 180 (set to `None` for no timeout). |

For example:

``` python
solver=[
    use_tools([computer(max_screenshots=2, timeout=300)]),
    generate()
]
```

#### Examples

Two of the Inspect examples demonstrate basic computer use:

- [computer](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/examples/computer/computer.py)
  — Three simple computing tasks as a minimal demonstration of computer
  use.

  ``` bash
  inspect eval examples/computer
  ```

- [intervention](https://github.com/UKGovernmentBEIS/inspect_ai/tree/main/examples/intervention/intervention.py)
  — Computer task driven interactively by a human operator.

  ``` bash
  inspect eval examples/intervention -T mode=computer --display conversation
  ```

### VNC Client

You can use a [VNC](https://en.wikipedia.org/wiki/VNC) connection to the
container to watch computer use in real-time. This requires some
additional port-mapping in the Docker compose file. You can define
dynamic port ranges for VNC (5900) and a browser based noVNC client
(6080) with the following `ports` entries:

**compose.yaml**

``` yaml
services:
  default:
    image: aisiuk/inspect-computer-tool:latest
    ports:
      - "5900"
      - "6080"
```

To connect to the container for a given sample, locate the sample in the
**Running Samples** UI and expand the sample info panel at the top:

![](images/vnc-port-info.png)

Click on the link for the noVNC browser client, or use a native VNC
client to connect to the VNC port. Note that the VNC server will take a
few seconds to start up so you should give it some time and attempt to
reconnect as required if the first connection fails.

The browser based client provides a view-only interface. If you use a
native VNC client you should also set it to “view only” so as to not
interfere with the model’s use of the computer. For example, for Real
VNC Viewer:

![](images/vnc-view-only.png)

### Approval

If the container you are using is connected to the Internet, you may
want to configure human approval for a subset of computer tool actions.
Here are the possible actions (specified using the `action` parameter to
the `computer` tool):

- `key`: Press a key or key-combination on the keyboard.
- `type`: Type a string of text on the keyboard.
- `cursor_position`: Get the current (x, y) pixel coordinate of the
  cursor on the screen.
- `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate
  on the screen.
- Example: execute(action=“mouse_move”, coordinate=(100, 200))
- `left_click`: Click the left mouse button.
- `left_click_drag`: Click and drag the cursor to a specified (x, y)
  pixel coordinate on the screen.
- `right_click`: Click the right mouse button.
- `middle_click`: Click the middle mouse button.
- `double_click`: Double-click the left mouse button.
- `screenshot`: Take a screenshot.

Here is an approval policy that requires approval for key combos
(e.g. `Enter` or a shortcut) and mouse clicks:

**approval.yaml**

``` yaml
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

Note that since this is a prefix match and there could be other
arguments, we don’t end the tool match pattern with a parentheses.

You can apply this policy using the `--approval` commmand line option:

``` bash
inspect eval computer.py --approval approval.yaml
```

### Tool Binding

The computer tool’s schema is based on the standard Anthropoic [computer
tool-type](https://docs.anthropic.com/en/docs/build-with-claude/computer-use#computer-tool).
When using Claude 3.5 the coputer tool will automatically bind to the
native Claude computer tool definition. This presumably provides
improved performance due to fine tuning on the use of the tool but we
have not verified this.

If you want to experiement with bypassing the native Claude computer
tool type and just register the computer tool as a normal function based
tool then specify the `--no-internal-tools` generation option as
follows:

``` bash
inspect eval computer.py --no-internal-tools
```

## Web Search

The `web_search()` tool provides models the ability to enhance their
context window by performing a search. By default web searches retrieve
10 results from a provider, uses a model to determine if the contents is
relevant then returns the top 3 relevant search results to the main
model. Here is the definition of the `web_search()` function:

``` python
def web_search(
    provider: Literal["google"] = "google",
    num_results: int = 3,
    max_provider_calls: int = 3,
    max_connections: int = 10,
    model: str | Model | None = None,
) -> Tool:
    ...
```

You can use the `web_search()` tool like this:

``` python
from inspect_ai.tool import web_search

solver=[
    use_tools(web_search()), 
    generate()
],
```

Web search options include:

- `provider`—Web search provider (currently only Google is supported,
  see below for instructions on setup and configuration for Google).

- `num_results`—How many search results to return to the main model
  (defaults to 5).

- `max_provider_calls`—Number of times to retrieve more links from the
  search provider in case previous ones were irrelevant (defaults to 3).

- `max_connections`—Maximum number of concurrent connections to the
  search API provider (defaults to 10).

- `model`—Model to use to determine if search results are relevant
  (defaults to the model currently being evaluated).

#### Google Provider

The `web_search()` tool uses [Google Programmable Search
Engine](https://programmablesearchengine.google.com/about/). To use it
you will therefore need to setup your own Google Programmable Search
Engine and also enable the [Programmable Search Element Paid
API](https://developers.google.com/custom-search/docs/paid_element).
Then, ensure that the following environment variables are defined:

- `GOOGLE_CSE_ID` — Google Custom Search Engine ID

- `GOOGLE_CSE_API_KEY` — Google API key used to enable the Search API
