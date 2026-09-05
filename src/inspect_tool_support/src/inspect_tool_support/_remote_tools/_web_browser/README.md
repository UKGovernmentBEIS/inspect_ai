## Headless Browser Tool

This directory contains an implementation for the Headless Browser Tool which can be used to test web browsing agents.

### Usage

#### 1. Start the Docker container

A JSON-RPC server exposing the headless browser will be launched automatically on starting of the docker container and will be ready to receive client requests.

#### 2. Send the command

The tool is driven through the inspect-tool-support CLI (the `web_*` commands below are dispatched over JSON-RPC by the server — see `json_rpc_methods.py`, `controller.py`, and `playwright_browser.py` in this directory):

```
# Inside the Docker container
$ inspect-tool-support [COMMAND] [args]
```

###### Commands

The following commands are available at the moment:

* **web_go \<URL\>** - goes to the specified url.
* **web_click \<ELEMENT_ID\>** - clicks on a given element. 
* **web_scroll \<up/down\>** - scrolls up or down one page.
* **web_forward** - navigates forward a page.
* **web_back** - navigates back a page.
* **web_refresh** - reloads current page (F5).
* **web_type \<ELEMENT_ID\> \<TEXT\>** - types the specified text into the input with the specified id.
* **web_type_submit \<ELEMENT_ID\> \<TEXT\>** - types the specified text into the input with the specified id and presses ENTER to submit the form.

#### 3. Read the resulting observations

The result will be printed out in _stdout_ in the following format:

```
# Inside the Docker container
error: <an ERROR message if one occurred>
info: <general info about the container>
web_url: <the URL of the page the browser is currently at>
web_at: <accessibility tree of the visible elements of the page>
```

### Design

The tool consists of the following components:

- _json_rpc_methods.py_ - JSON-RPC method definitions exposed to the client.
- _controller.py_ - the controller that maps incoming commands to browser actions.
- _playwright_browser.py_ - a wrapper over the sync Playwright API driving the headless chromium browser.
