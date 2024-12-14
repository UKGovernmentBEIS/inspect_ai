from textwrap import dedent

RECORD_SESSION_DIR = "/var/tmp/inspect-user-sessions"


def record_session_setup() -> str:
    return dedent(f"""
    # record human agent session transcript (do this only for interative shell in terminals)

    # Only run if shell is interactive
    case $- in
        *i*) ;;
        *) return ;;
    esac

    # Only run if attached to a terminal
    if ! tty -s; then
        return
    fi

    if [ -z "$SCRIPT_RUNNING" ]; then
        export SCRIPT_RUNNING=1
        LOGDIR={RECORD_SESSION_DIR}
        mkdir -p "$LOGDIR"
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        INPUTFILE="$LOGDIR/$(whoami)_$TIMESTAMP.input"
        OUTPUTFILE="$LOGDIR/$(whoami)_$TIMESTAMP.output"
        TIMINGFILE="$LOGDIR/$(whoami)_$TIMESTAMP.timing"
        exec script -q -f -m advanced -I "$INPUTFILE" -O "$OUTPUTFILE" -T "$TIMINGFILE" -c "bash --login -i"
    fi
    """).lstrip()
