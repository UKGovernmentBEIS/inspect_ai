"""Dump a sample's events from an eval log, flat and as a span hierarchy.

Usage:
    python scripts/dump_events.py <path-to-.eval> [--sample ID] [--epoch N]

Opens the given eval log, selects one sample, and prints its events twice:
once as a flat ordered list, once nested by span. With no ``--sample`` /
``--epoch`` the first sample in the log is used; ``--sample`` selects by
sample id and ``--epoch`` by epoch (combine them to disambiguate a sample
that ran for multiple epochs). Most events render as
``<event.event> <name-or-identifier>``; spans also show a short id and parent
id so the flat and hierarchical views can be correlated.
"""

from __future__ import annotations

import argparse

from inspect_ai.event import EventTreeSpan, event_tree
from inspect_ai.event._event import Event
from inspect_ai.log import EvalSample, read_eval_log


def _sid(span_id: str | None) -> str:
    """Short, stable rendering of a span id for eyeballing."""
    return span_id[:4] if span_id else "----"


# For events with no `name`, surface the natural identifier (first match
# wins) so busy leaf events stay legible: tool->function, model->model,
# sandbox->action, info->source.
_ID_FIELDS = ("function", "model", "action", "source")


def _event_label(e: Event) -> str:
    """``<event> <name-or-identifier>`` for most events; id/parent for spans."""
    name = getattr(e, "name", None)
    type_ = getattr(e, "type", None)
    label: str = e.event
    if name is not None:
        label += f" {name!r}"
    else:
        for field in _ID_FIELDS:
            value = getattr(e, field, None)
            if value is not None:
                label += f" {value!r}"
                break
    # checkpoint events render as `checkpoint N`
    if e.event == "checkpoint":
        cid = getattr(e, "checkpoint_id", None)
        if cid is not None:
            label += f" {cid}"
    # for sandbox exec, show the first 50 chars of the command line
    cmd = getattr(e, "cmd", None)
    if e.event == "sandbox" and cmd:
        label += f" {cmd[:50]!r}" + ("…" if len(cmd) > 50 else "")
    # for a tool call, show the error (if it failed) or the first 50 chars of
    # the result
    if e.event == "tool":
        error = getattr(e, "error", None)
        if error is not None:
            label += f" ERROR:{error.type}"
        else:
            result = str(getattr(e, "result", "")).replace("\n", " ")
            if result:
                label += f" -> {result[:50]!r}" + ("…" if len(result) > 50 else "")
    # `[function]` on tool events is noise; keep `[type]` for span markers
    if type_ is not None and type_ != name and e.event != "tool":
        label += f" [{type_}]"
    # span markers carry the span identity the tree is built from
    if e.event in ("span_begin", "span_end"):
        eid = getattr(e, "id", None)
        parent = getattr(e, "parent_id", None)
        label += f"  id={_sid(eid)}"
        if e.event == "span_begin":
            label += f" parent={_sid(parent)}"
    return label


def dump_flat(events: list[Event]) -> None:
    print("=" * 70)
    print(f"FLAT  ({len(events)} events)")
    print("=" * 70)
    for i, e in enumerate(events):
        print(f"{i:>4}  span={_sid(e.span_id)}  {_event_label(e)}")


def dump_tree(events: list[Event]) -> None:
    print()
    print("=" * 70)
    print("HIERARCHY (by span)")
    print("=" * 70)

    def walk(nodes: list[EventTreeSpan | Event], depth: int) -> None:
        indent = "  " * depth
        for node in nodes:
            if isinstance(node, EventTreeSpan):
                open_marker = "" if node.end is not None else "  (unclosed)"
                print(
                    f"{indent}SPAN {node.type!r} {node.name!r} "
                    f"id={_sid(node.id)} parent={_sid(node.parent_id)}{open_marker}"
                )
                walk(node.children, depth + 1)
            else:
                print(f"{indent}{_event_label(node)}")

    walk(event_tree(events), 0)


def _select_sample(
    samples: list[EvalSample], sample_id: str | None, epoch: int | None
) -> EvalSample:
    """Pick a sample by id and/or epoch; default to the first sample.

    ``sample_id`` is matched against ``str(sample.id)`` (ids may be int or
    str). With both unset the first sample is returned.
    """
    matches = [
        s
        for s in samples
        if (sample_id is None or str(s.id) == sample_id)
        and (epoch is None or s.epoch == epoch)
    ]
    if not matches:
        want = f"id={sample_id!r} epoch={epoch}"
        have = ", ".join(f"(id={s.id!r}, epoch={s.epoch})" for s in samples)
        raise SystemExit(f"no sample matching {want}; log has: {have}")
    return matches[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Dump a sample's events.")
    parser.add_argument("path", help="path to the .eval log")
    parser.add_argument(
        "--sample", "-s", help="sample id (default: first sample in the log)"
    )
    parser.add_argument(
        "--epoch", "-e", type=int, help="epoch (combine with --sample to disambiguate)"
    )
    args = parser.parse_args()

    log = read_eval_log(args.path)
    if not log.samples:
        raise SystemExit(f"no samples in {args.path}")
    sample = _select_sample(log.samples, args.sample, args.epoch)
    events = list(sample.events)

    print(f"log:    {args.path}")
    print(f"sample: id={sample.id!r} epoch={sample.epoch}")
    dump_flat(events)
    dump_tree(events)


if __name__ == "__main__":
    main()
