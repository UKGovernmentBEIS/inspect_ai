from textwrap import dedent

RECORD_SESSION_DIR = "/var/tmp/inspect-user-sessions"


def record_session_setup() -> str:
    return dedent(f"""
    # record human agent session transcript
    if [ -z "$SCRIPT_RUNNING" ]; then
        export SCRIPT_RUNNING=1
        LOGDIR={RECORD_SESSION_DIR}
        mkdir -p "$LOGDIR"
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        LOGFILE="$LOGDIR/$(whoami)_$TIMESTAMP.log"
        TIMINGFILE="$LOGDIR/$(whoami)_$TIMESTAMP.time"
        exec script -q -f -T "$TIMINGFILE" "$LOGFILE" -c "bash --login -i"
    fi
    """).lstrip()
