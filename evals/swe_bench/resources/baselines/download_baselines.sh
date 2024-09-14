# Download the swe-bench baselines. NOTE: THEY ARE QUITE LARGE. 
git clone https://github.com/swe-bench/experiments /tmp/swebench_baselines
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
# Copy to current directory
cp -r /tmp/swebench_baselines/evaluation/verified/20240620_sweagent_claude3.5sonnet $SCRIPT_DIR
# Can add other files in /tmp/swebenchbaselines/evaluations/... here