#### Failing

This is for testing in the sample target container with the PyInstaller bundle.

```bash
# Build the bundled executable and put it into src/inspect_ai/binaries
python src/inspect_ai/tool/tool_support/build_within_container.py --arch arm64 --browser

# Launch the container from the host
docker run --platform linux/amd64 --rm -d -v "/Users/ericpatey/code/inspect_ai/src/inspect_ai/binaries:/binaries" debian:bookworm-slim bash -lc 'tail -f /dev/null'

# Do the test within the container
cd /binaries
./inspect-tool-support-arm64-v667+browser-dev test
```

#### Succeeding

This is the same code but unbundled

```bash
# launch the container
docker run --platform linux/amd64 --rm -d -v "/Users/ericpatey/code/inspect_ai/src/inspect_tool_support/src/inspect_tool_support/_cli/test_chromium.py:/tmp/test_chromium.py" debian:bookworm-slim bash -lc 'tail -f /dev/null'


# in the container - one time env setup
apt-get update && apt-get install -y python3 python3.11-venv
python3 -m venv /tmp/.venv
source /tmp/.venv/bin/activate
pip install playwright
playwright install chromium-headless-shell
playwright install-deps

# as many times as you want

python /tmp/test_chromium.py

```
