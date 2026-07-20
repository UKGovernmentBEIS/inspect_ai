#!/usr/bin/env python3
"""Hourly Atlas sync — external-review discovery + upstream state sync.

Two tasks (design: meridianlabs-ai/agents design/atlas-tracking.md → "The
hourly Atlas sync"):

1. Discovery: open upstream PRs review-requested-to / assigned-to REVIEWER,
   authored by external community contributors (not org members, not bots),
   not already tracked -> create a proxy issue in the fork (External label,
   Stage=Human Review, Upstream PR field).
2. State sync: every OPEN fork issue on Atlas with a non-empty "Upstream PR"
   field -> read the upstream PR and advance the stage:
     - External proxies: merged/closed -> close proxy (Done); while in
       Awaiting Contributor, contributor activity newer than the reviewer's
       last activity (or a re-review request) -> Human Review.
     - Promotions: APPROVED -> Awaiting Merge; CHANGES_REQUESTED -> Human
       Review; approval dismissed -> Awaiting Merge->Sign-off only; merged ->
       close (Done); closed unmerged -> Human Review + comment.

Deterministic; runs as the machine account (GH_TOKEN=MARVIN_TOKEN). Per-item
failures warn and continue. Every write is idempotent.
"""

import json
import os
import re
import subprocess
import sys

UPSTREAM = "UKGovernmentBEIS/inspect_ai"
FORK = "meridianlabs-ai/inspect_ai"
ORG = "meridianlabs-ai"
REVIEWER = os.environ.get("REVIEWER", "ransomr")

PROJECT_ID = "PVT_kwDOC7YMCM4BU68p"
PROJECT_NUMBER = 1
STAGE_FIELD = "PVTSSF_lADOC7YMCM4BU68pzhYZEwY"
STAGE_OPTIONS = {
    "Agent Working": "18c9cd89",
    "Human Review": "d261eb6b",
    "Sign-off": "da6137e6",
    "Awaiting Merge": "add17478",
    "Awaiting Contributor": "39c05a50",
}
STATUS_FIELD = "PVTSSF_lADOC7YMCM4BU68pzhKizZM"
STATUS_OPTIONS = {"Todo": "f75ad846", "In progress": "47fc9ee4", "Done": "98236657"}
UPSTREAM_PR_FIELD = "PVTF_lADOC7YMCM4BU68pzhYZp9Q"

# Stages where the ball is upstream — the promotion mapping's whole domain.
TAIL_STAGES = ("Sign-off", "Awaiting Merge")

actions: list = []  # human-readable log for the job summary
pending_chips: list = []


def gh(*args: str) -> str:
    res = subprocess.run(["gh", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}...: {res.stderr.strip()[:400]}")
    return res.stdout


def gh_json(*args: str):
    return json.loads(gh(*args))


def gql(query: str, **variables):
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += (["-F", f"{k}={v}"] if isinstance(v, (int, bool)) else ["-f", f"{k}={v}"])
    out = gh_json(*args)
    if out.get("errors"):
        raise RuntimeError(f"graphql: {out['errors'][0].get('message', out['errors'])[:300]}")
    return out["data"]


def is_org_member(login: str) -> bool:
    """Only a real 404 means "not a member" — any other failure (rate limit,
    5xx, network) raises, so per-item isolation retries next run instead of
    misclassifying a teammate as external."""
    res = subprocess.run(
        ["gh", "api", f"orgs/{ORG}/members/{login}"], capture_output=True, text=True
    )
    if res.returncode == 0:
        return True
    if "HTTP 404" in res.stderr:
        return False
    raise RuntimeError(f"org membership check failed for {login}: {res.stderr.strip()[:200]}")


def set_single_select(item_id: str, field_id: str, option_id: str) -> None:
    gql(
        """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
             updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,
               value:{singleSelectOptionId:$o}}){projectV2Item{id}}}""",
        p=PROJECT_ID, i=item_id, f=field_id, o=option_id,
    )


def set_text(item_id: str, field_id: str, text: str) -> None:
    gql(
        """mutation($p:ID!,$i:ID!,$f:ID!,$t:String!){
             updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,
               value:{text:$t}}){projectV2Item{id}}}""",
        p=PROJECT_ID, i=item_id, f=field_id, t=text,
    )


def clear_field(item_id: str, field_id: str) -> None:
    gql(
        """mutation($p:ID!,$i:ID!,$f:ID!){
             clearProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f})
             {projectV2Item{id}}}""",
        p=PROJECT_ID, i=item_id, f=field_id,
    )


def set_stage(item_id: str, stage: str, current) -> bool:
    """Idempotent stage write; active stages also nudge Status to In progress."""
    if current == stage:
        return False
    set_single_select(item_id, STAGE_FIELD, STAGE_OPTIONS[stage])
    set_single_select(item_id, STATUS_FIELD, STATUS_OPTIONS["In progress"])
    return True


# ---------------------------------------------------------------- discovery


def tracked_proxies() -> dict:
    """Upstream URL -> proxy info for every External proxy, open OR closed
    (closed ones keep a Done proxy from being recreated)."""
    out = {}
    issues = gh_json(
        "api", f"repos/{FORK}/issues?labels=External&state=all&per_page=100", "--paginate"
    )
    for i in issues:
        m = re.search(r"https://github\.com/\S+/pull/\d+", i.get("body") or "")
        if m:
            out[m.group(0)] = {
                "number": i["number"],
                "node_id": i["node_id"],
                "open": i["state"] == "open",
            }
    return out


def ensure_on_board(node_id: str, url: str):
    """Idempotently make sure a proxy is on Atlas with its field and a stage —
    heals a previous run that created the issue but died before the board
    writes (the URL is already in the body, so dedup alone would skip it
    forever and state sync would never see it)."""
    item = gql(
        """mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}""",
        p=PROJECT_ID, c=node_id,
    )["addProjectV2ItemById"]["item"]["id"]
    cur = gql(
        """query($i:ID!){ node(id:$i){ ... on ProjectV2Item {
             stage: fieldValueByName(name:"Stage"){
               ... on ProjectV2ItemFieldSingleSelectValue{name}}
             up: fieldValueByName(name:"Upstream PR"){
               ... on ProjectV2ItemFieldTextValue{text}} }}}""",
        i=item,
    )["node"]
    healed = False
    if not ((cur.get("up") or {}).get("text") or "").strip():
        set_text(item, UPSTREAM_PR_FIELD, url)
        healed = True
    if not (cur.get("stage") or {}).get("name"):
        set_stage(item, "Human Review", None)
        healed = True
    return healed


def candidate_prs():
    seen, out = set(), []
    for q in (f"review-requested:{REVIEWER}", f"assignee:{REVIEWER}"):
        res = gh_json(
            "api",
            f"search/issues?q=repo:{UPSTREAM}+type:pr+state:open+{q}&per_page=100",
        )
        for item in res.get("items", []):
            if item["number"] in seen:
                continue
            seen.add(item["number"])
            out.append(item)
    return out


def discover() -> None:
    tracked = tracked_proxies()
    for pr in candidate_prs():
        num, title = pr["number"], pr["title"]
        url = f"https://github.com/{UPSTREAM}/pull/{num}"
        author = pr["user"]["login"]
        try:
            if url in tracked:
                # Heal a partially-seeded OPEN proxy (issue exists, board
                # writes failed); closed proxies stay untouched.
                if tracked[url]["open"] and ensure_on_board(tracked[url]["node_id"], url):
                    actions.append(f"healed proxy #{tracked[url]['number']} for upstream #{num}")
                continue
            if author.endswith("[bot]") or author == REVIEWER or is_org_member(author):
                continue
            body = (
                f"Tracking review of external contributor PR by {author} in upstream inspect_ai.\n\n"
                f"Upstream PR: {url}\n\n"
                "Labeled `External`; created by the hourly Atlas sync. Stage starts at "
                "**Human Review** (the review request is with the reviewer); move it to "
                "**Awaiting Contributor** after reviewing."
            )
            issue = gh_json(
                "api", f"repos/{FORK}/issues",
                "-f", f"title=Review upstream #{num}: {title}",
                "-f", f"body={body}",
                "-f", "labels[]=External",
                "-f", f"assignees[]={REVIEWER}",
            )
            ensure_on_board(issue["node_id"], url)
            actions.append(f"created proxy #{issue['number']} for upstream #{num} ({author})")
            pending_chips.append(f"#{issue['number']} -> {url}")
        except Exception as e:  # noqa: BLE001 — per-item isolation
            print(f"::warning::discovery failed for upstream #{num}: {e}")


# --------------------------------------------------------------- state sync

def board_items():
    """Open fork issues on Atlas with a non-empty Upstream PR field."""
    after, rows = "", []
    while True:
        data = gql(
            """query($p:ID!,$after:String){ node(id:$p){ ... on ProjectV2 {
                 items(first:100, after:$after){
                   pageInfo{hasNextPage endCursor}
                   nodes{
                     id
                     stage: fieldValueByName(name:"Stage"){
                       ... on ProjectV2ItemFieldSingleSelectValue{name}}
                     up: fieldValueByName(name:"Upstream PR"){
                       ... on ProjectV2ItemFieldTextValue{text}}
                     content{ ... on Issue{
                       number state repository{nameWithOwner}
                       assignees(first:10){nodes{login}}
                       labels(first:20){nodes{name}} }}}}}}}""",
            p=PROJECT_ID, **({"after": after} if after else {}),
        )["node"]["items"]
        for n in data["nodes"]:
            c = n.get("content") or {}
            up = (n.get("up") or {}).get("text", "").strip()
            if (
                c.get("state") == "OPEN"
                and c.get("repository", {}).get("nameWithOwner") == FORK
                and up
                # Pilot scoping: only sync issues assigned to the reviewer.
                and any(
                    a["login"] == REVIEWER for a in c["assignees"]["nodes"]
                )
            ):
                rows.append({
                    "item": n["id"],
                    "issue": c["number"],
                    "stage": (n.get("stage") or {}).get("name"),
                    "url": up,
                    "external": any(lbl["name"] == "External" for lbl in c["labels"]["nodes"]),
                })
        if not data["pageInfo"]["hasNextPage"]:
            return rows
        after = data["pageInfo"]["endCursor"]


def upstream_pr(url: str):
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", url)
    if not m:
        raise ValueError(f"bad upstream URL {url}")
    owner, repo, num = m.group(1), m.group(2), int(m.group(3))
    d = gql(
        """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){
             pullRequest(number:$n){
               state merged reviewDecision author{login}
               reviewRequests(first:20){nodes{requestedReviewer{... on User{login}}}}
             }}}""",
        o=owner, r=repo, n=num,
    )["repository"]["pullRequest"]
    d["_ref"] = (owner, repo, num)
    return d


def latest_activity(owner: str, repo: str, num: int) -> tuple[str, str]:
    """(latest author-activity ts, latest reviewer-activity ts) on the PR."""
    author_ts, reviewer_ts = "", ""
    d = gql(
        """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){
             pullRequest(number:$n){
               author{login}
               comments(last:50){nodes{author{login} createdAt}}
               reviews(last:50){nodes{author{login} submittedAt}}
               reviewThreads(last:50){nodes{comments(last:20){nodes{author{login} createdAt}}}}
             }}}""",
        o=owner, r=repo, n=num,
    )["repository"]["pullRequest"]
    pr_author = (d.get("author") or {}).get("login", "")
    events = []
    events += [(c["author"], c["createdAt"]) for c in d["comments"]["nodes"]]
    events += [(r["author"], r["submittedAt"]) for r in d["reviews"]["nodes"] if r.get("submittedAt")]
    for t in d["reviewThreads"]["nodes"]:
        events += [(c["author"], c["createdAt"]) for c in t["comments"]["nodes"]]
    for who, ts in events:
        login = (who or {}).get("login", "")
        if login == pr_author and ts > author_ts:
            author_ts = ts
        if login == REVIEWER and ts > reviewer_ts:
            reviewer_ts = ts
    return author_ts, reviewer_ts


def close_issue(number: int, comment: str) -> None:
    gh("api", f"repos/{FORK}/issues/{number}/comments", "-f", f"body={comment}")
    gh("api", "-X", "PATCH", f"repos/{FORK}/issues/{number}", "-f", "state=closed")


def comment(number: int, body: str) -> None:
    gh("api", f"repos/{FORK}/issues/{number}/comments", "-f", f"body={body}")


def sync_item(row) -> None:
    pr = upstream_pr(row["url"])
    owner, repo, num = pr["_ref"]
    stage, item, issue = row["stage"], row["item"], row["issue"]

    if pr["merged"]:
        close_issue(issue, f"Upstream PR {row['url']} was merged — closing. (Atlas sync)")
        clear_field(item, STAGE_FIELD)
        set_single_select(item, STATUS_FIELD, STATUS_OPTIONS["Done"])
        actions.append(f"#{issue}: upstream merged -> closed (Done)")
        return

    if pr["state"] == "CLOSED":  # closed without merge
        if row["external"]:
            close_issue(issue, f"Upstream PR {row['url']} was closed unmerged — closing. (Atlas sync)")
            clear_field(item, STAGE_FIELD)
            set_single_select(item, STATUS_FIELD, STATUS_OPTIONS["Done"])
            actions.append(f"#{issue}: upstream closed -> proxy closed")
        elif stage in TAIL_STAGES and set_stage(item, "Human Review", stage):
            # Gated to the tail so a stage the driver parked elsewhere is left
            # alone — and the comment can't be re-posted on an hourly bounce.
            comment(issue, f"Upstream PR {row['url']} was closed unmerged — needs a human decision. (Atlas sync)")
            actions.append(f"#{issue}: upstream closed unmerged -> Human Review")
        return

    rerequested = any(
        (n.get("requestedReviewer") or {}).get("login")
        for n in pr["reviewRequests"]["nodes"]
    )
    if row["external"]:
        if stage == "Awaiting Contributor":
            author_ts, reviewer_ts = latest_activity(owner, repo, num)
            rerequested_to_me = any(
                (n.get("requestedReviewer") or {}).get("login") == REVIEWER
                for n in pr["reviewRequests"]["nodes"]
            )
            if (author_ts and author_ts > reviewer_ts) or rerequested_to_me:
                if set_stage(item, "Human Review", stage):
                    actions.append(f"#{issue}: contributor responded -> Human Review")
        return

    # Promotion tail — only while the ball is genuinely upstream. Stages a
    # human parked elsewhere (Agent Working, Human Review, ...) are out of this
    # mapping's domain: reviewDecision is sticky (CHANGES_REQUESTED persists
    # until a re-review), so acting from any stage would drag parked items back
    # here every hour.
    if stage not in TAIL_STAGES:
        return
    decision = pr.get("reviewDecision")
    if decision == "CHANGES_REQUESTED" and rerequested:
        # Stale: fixes were pushed and a re-review requested; the recorded
        # decision persists until the reviewer acts. Treat as review-pending.
        decision = None
    if decision == "APPROVED":
        if set_stage(item, "Awaiting Merge", stage):
            actions.append(f"#{issue}: upstream approved -> Awaiting Merge")
    elif decision == "CHANGES_REQUESTED":
        if set_stage(item, "Human Review", stage):
            actions.append(f"#{issue}: upstream changes requested -> Human Review")
    else:  # REVIEW_REQUIRED / None: only undo a stale Awaiting Merge
        if stage == "Awaiting Merge" and set_stage(item, "Sign-off", stage):
            actions.append(f"#{issue}: approval dismissed -> Sign-off")


def main() -> int:
    discover()
    for row in board_items():
        try:
            sync_item(row)
        except Exception as e:  # noqa: BLE001 — per-item isolation
            print(f"::warning::sync failed for #{row['issue']}: {e}")

    print("\n=== Atlas sync summary ===")
    for a in actions or ["no changes"]:
        print(f"- {a}")
    if pending_chips:
        print("\nProxies pending a clickable chip (run link-upstream-chips locally):")
        for p in pending_chips:
            print(f"- {p}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### Atlas sync\n")
            for a in actions or ["no changes"]:
                f.write(f"- {a}\n")
            if pending_chips:
                f.write("\n**Pending chips** (run `link-upstream-chips` locally):\n")
                for p in pending_chips:
                    f.write(f"- {p}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
