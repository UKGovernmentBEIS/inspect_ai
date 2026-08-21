#!/usr/bin/env python3
"""Hourly Atlas sync — external-review discovery + upstream state sync.

Two tasks (design: meridianlabs-ai/agents design/atlas-tracking.md → "The
hourly Atlas sync"):

1. Discovery: open upstream PRs review-requested-to / assigned-to REVIEWER,
   authored by external community contributors (not org members, not bots),
   not already tracked -> create a proxy issue in the fork (External label,
   Stage=Review, Upstream PR field), then post @review on it so the external
   review is already running before a human opens the proxy.
2. State sync: every OPEN fork issue on Atlas with a non-empty "Upstream PR"
   field -> read the upstream PR and advance the stage:
     - External proxies: merged/closed -> close proxy (Done); APPROVED ->
       Merge (the merge-approved-prs queue; dismiss the approval or request
       changes to pull one back, sticky APPROVED re-queues a moved card);
       in Merge without a standing approval -> Review; while in Contributor,
       contributor activity newer than the reviewer's last activity (or a
       re-review request) -> Review.
     - Promotions: APPROVED -> Merge (gated on any ts-mono companion
       being merged or approved); CHANGES_REQUESTED -> Review;
       approval dismissed -> Merge->Sign-off only; merged ->
       close (Done); closed unmerged -> Review + comment.

Deterministic; runs as the machine account (GH_TOKEN=MARVIN_TOKEN). Per-item
failures warn and continue. Every write is idempotent except the @review
trigger comment, which is at-most-once: only the create path posts it (dedup
skips tracked proxies, and heal never re-requests), so a failure there is
surfaced as a "review request FAILED" action + warning rather than retried —
the manual re-run path is commenting @review on the proxy.
"""

import json
import os
import re
import subprocess
import sys

UPSTREAM = "UKGovernmentBEIS/inspect_ai"
FORK = "meridianlabs-ai/inspect_ai"
TS_MONO = "meridianlabs-ai/ts-mono"
ORG = "meridianlabs-ai"
REVIEWER = os.environ.get("REVIEWER", "ransomr")

PROJECT_ID = "PVT_kwDOC7YMCM4BU68p"
PROJECT_NUMBER = 1
STAGE_FIELD = "PVTSSF_lADOC7YMCM4BU68pzhYZEwY"
STAGE_OPTIONS = {
    "Agent": "18c9cd89",
    "Review": "d261eb6b",
    "Sign-off": "da6137e6",
    "Merge": "add17478",
    "Contributor": "39c05a50",
}
STATUS_FIELD = "PVTSSF_lADOC7YMCM4BU68pzhKizZM"
STATUS_OPTIONS = {"Todo": "f75ad846", "In progress": "47fc9ee4", "Done": "98236657"}
UPSTREAM_PR_FIELD = "PVTF_lADOC7YMCM4BU68pzhYZp9Q"

# Stages where the ball is upstream — the promotion mapping's whole domain.
TAIL_STAGES = ("Sign-off", "Merge")

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
        args += ["-F", f"{k}={v}"] if isinstance(v, (int, bool)) else ["-f", f"{k}={v}"]
    out = gh_json(*args)
    if out.get("errors"):
        raise RuntimeError(
            f"graphql: {out['errors'][0].get('message', out['errors'])[:300]}"
        )
    return out["data"]


def is_org_member(login: str) -> bool:
    """Only a real 404 means "not a member".

    Any other failure (rate limit, 5xx, network) raises, so per-item isolation
    retries next run instead of misclassifying a teammate as external.
    """
    res = subprocess.run(
        ["gh", "api", f"orgs/{ORG}/members/{login}"], capture_output=True, text=True
    )
    if res.returncode == 0:
        return True
    if "HTTP 404" in res.stderr:
        return False
    raise RuntimeError(
        f"org membership check failed for {login}: {res.stderr.strip()[:200]}"
    )


def set_single_select(item_id: str, field_id: str, option_id: str) -> None:
    gql(
        """mutation($p:ID!,$i:ID!,$f:ID!,$o:String!){
             updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,
               value:{singleSelectOptionId:$o}}){projectV2Item{id}}}""",
        p=PROJECT_ID,
        i=item_id,
        f=field_id,
        o=option_id,
    )


def set_text(item_id: str, field_id: str, text: str) -> None:
    gql(
        """mutation($p:ID!,$i:ID!,$f:ID!,$t:String!){
             updateProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f,
               value:{text:$t}}){projectV2Item{id}}}""",
        p=PROJECT_ID,
        i=item_id,
        f=field_id,
        t=text,
    )


def clear_field(item_id: str, field_id: str) -> None:
    gql(
        """mutation($p:ID!,$i:ID!,$f:ID!){
             clearProjectV2ItemFieldValue(input:{projectId:$p,itemId:$i,fieldId:$f})
             {projectV2Item{id}}}""",
        p=PROJECT_ID,
        i=item_id,
        f=field_id,
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
    """Upstream URL -> proxy info for every External proxy, open OR closed.

    Closed ones are included to keep a Done proxy from being recreated.
    """
    out = {}
    issues = gh_json(
        "api",
        f"repos/{FORK}/issues?labels=External&state=all&per_page=100",
        "--paginate",
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
    """Idempotently make sure a proxy is on Atlas with its field and a stage.

    Heals a previous run that created the issue but died before the board
    writes (the URL is already in the body, so dedup alone would skip it
    forever and state sync would never see it).
    """
    item = gql(
        """mutation($p:ID!,$c:ID!){addProjectV2ItemById(input:{projectId:$p,contentId:$c}){item{id}}}""",
        p=PROJECT_ID,
        c=node_id,
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
        set_stage(item, "Review", None)
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
                if tracked[url]["open"] and ensure_on_board(
                    tracked[url]["node_id"], url
                ):
                    actions.append(
                        f"healed proxy #{tracked[url]['number']} for upstream #{num}"
                    )
                continue
            if author.endswith("[bot]") or author == REVIEWER or is_org_member(author):
                continue
            body = (
                f"Tracking review of external contributor PR by {author} in upstream inspect_ai.\n\n"
                f"Upstream PR: {url}\n\n"
                "Labeled `External`; created by the hourly Atlas sync, which also "
                "requests an automated external review below — its findings land on "
                "this issue. Stage starts at **Review**; move it to **Contributor** "
                "after relaying feedback."
            )
            issue = gh_json(
                "api",
                f"repos/{FORK}/issues",
                "-f",
                f"title=Review upstream #{num}: {title}",
                "-f",
                f"body={body}",
                "-f",
                "labels[]=External",
                "-f",
                f"assignees[]={REVIEWER}",
            )
            ensure_on_board(issue["node_id"], url)
            # Kick off the automated external review immediately: marvin's
            # @review comment fires the reviewer's external mode (word-boundary
            # trigger; External label + upstream URL already in the body), so
            # findings are waiting on the proxy by the time a human looks.
            # Isolated try: this is the one write the heal path cannot recover
            # (dedup skips fully-boarded proxies), and a transient failure here
            # must not mislabel the successful creation as a failed item.
            try:
                comment(issue["number"], "@review")
                review_note = "review requested"
            except Exception as e:  # noqa: BLE001
                review_note = "review request FAILED — trigger @review manually"
                print(
                    f"::warning::auto-@review failed on proxy #{issue['number']}: {e}"
                )
            actions.append(
                f"created proxy #{issue['number']} for upstream #{num} ({author}); {review_note}"
            )
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
            p=PROJECT_ID,
            **({"after": after} if after else {}),
        )["node"]["items"]
        for n in data["nodes"]:
            c = n.get("content") or {}
            up = (n.get("up") or {}).get("text", "").strip()
            if (
                c.get("state") == "OPEN"
                and c.get("repository", {}).get("nameWithOwner") == FORK
                and up
            ):
                # Pilot scoping: only sync issues assigned to the reviewer —
                # but log the skips: this filter also gates the close-on-merge
                # housekeeping, so a proxy that lost its assignment would
                # otherwise become an invisible zombie.
                if not any(a["login"] == REVIEWER for a in c["assignees"]["nodes"]):
                    actions.append(
                        f"#{c['number']}: skipped (has Upstream PR but not assigned to {REVIEWER})"
                    )
                    continue
                rows.append(
                    {
                        "item": n["id"],
                        "issue": c["number"],
                        "stage": (n.get("stage") or {}).get("name"),
                        "url": up,
                        "external": any(
                            lbl["name"] == "External" for lbl in c["labels"]["nodes"]
                        ),
                    }
                )
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
               state merged reviewDecision headRefName author{login}
               reviewRequests(first:20){nodes{requestedReviewer{... on User{login}}}}
               requestEvents: timelineItems(itemTypes:[REVIEW_REQUESTED_EVENT], last:20){
                 nodes{... on ReviewRequestedEvent{createdAt}}}
               changesReviews: reviews(states:[CHANGES_REQUESTED], last:10){
                 nodes{submittedAt}}
             }}}""",
        o=owner,
        r=repo,
        n=num,
    )["repository"]["pullRequest"]
    d["_ref"] = (owner, repo, num)
    # Latest review-request event and latest changes-requested review, as ISO
    # timestamps ("" when absent; ISO compares lexicographically). A *pending*
    # request alone is not a re-request: a second reviewer's never-consumed
    # initial request keeps reviewDecision CHANGES_REQUESTED and the request
    # queue non-empty forever — only a request event NEWER than the latest
    # changes-requested review is the driver handing back.
    d["_req_ts"] = max(
        (n["createdAt"] for n in d["requestEvents"]["nodes"]), default=""
    )
    d["_changes_ts"] = max(
        (n["submittedAt"] for n in d["changesReviews"]["nodes"]), default=""
    )
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
        o=owner,
        r=repo,
        n=num,
    )["repository"]["pullRequest"]
    pr_author = (d.get("author") or {}).get("login", "")
    events = []
    events += [(c["author"], c["createdAt"]) for c in d["comments"]["nodes"]]
    events += [
        (r["author"], r["submittedAt"])
        for r in d["reviews"]["nodes"]
        if r.get("submittedAt")
    ]
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


def companion_pr(issue: int, head_ref: str):
    """The ts-mono companion PR folded into this issue's stage, or None.

    Join key (design: agents design/atlas-tracking.md -> "Multi-repo
    issues"): an explicit `Companion PR: <url>` line in the anchor issue
    body wins; otherwise the branch-name convention — the ts-mono PR whose
    head equals the upstream PR's headRefName (the dev agent names
    companion branches identically in both repos).
    """
    body = (
        gh_json("api", f"repos/{FORK}/issues/{issue}", "--jq", "{body: .body}")["body"]
        or ""
    )
    # precedence: an explicit URL wins over the `none` opt-out, which wins
    # over the branch-name convention
    m = re.search(
        r"Companion PR:\s*(https://github\.com/[^/\s]+/[^/\s]+/pull/\d+)",
        body,
        re.I,
    )
    if not m and re.search(r"Companion PR:\s*none\b", body, re.I):
        return None  # explicit opt-out: no companion, convention disabled
    if m:
        cm = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", m.group(1))
        owner, repo, num = cm.group(1), cm.group(2), int(cm.group(3))
        d = gql(
            """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){
                 pullRequest(number:$n){number state merged reviewDecision
                   latestOpinionatedReviews(first:10){nodes{state}}}}}""",
            o=owner,
            r=repo,
            n=num,
        )["repository"]["pullRequest"]
        d["_repo"] = f"{owner}/{repo}"
        return d
    if not head_ref:
        return None
    owner, repo = TS_MONO.split("/")
    nodes = gql(
        """query($o:String!,$r:String!,$h:String!){ repository(owner:$o,name:$r){
             pullRequests(headRefName:$h, first:5, orderBy:{field:UPDATED_AT,direction:DESC}){
               nodes{number state merged reviewDecision
                 latestOpinionatedReviews(first:10){nodes{state}}}}}}""",
        o=owner,
        r=repo,
        h=head_ref,
    )["repository"]["pullRequests"]["nodes"]
    # prefer an open PR; else the most recently updated (merged counts)
    pick = next((n for n in nodes if n["state"] == "OPEN"), nodes[0] if nodes else None)
    if pick:
        pick["_repo"] = TS_MONO
    return pick


def companion_approved(comp) -> bool:
    """Approval that works without required-review branch protection.

    `reviewDecision` is null on repos without a required-review rule
    (ts-mono), even with APPROVED reviews standing — so fall back to the
    per-reviewer latest opinionated reviews. A standing
    CHANGES_REQUESTED (either surface) blocks: the fallback must not be
    LOOSER than the decision it substitutes for.
    """
    decision = comp.get("reviewDecision")
    if decision is not None:
        # any non-null decision is authoritative: REVIEW_REQUIRED means the
        # repo's rule (approval count, CODEOWNERS, writer-only) is UNMET even
        # if some approval stands — the fallback is only for repos with no
        # rule at all, where the decision is null.
        return decision == "APPROVED"
    states = [
        r.get("state")
        for r in (comp.get("latestOpinionatedReviews") or {}).get("nodes") or []
    ]
    return "APPROVED" in states and "CHANGES_REQUESTED" not in states


def companion_blocks_merge(issue: int, pr) -> bool:
    """True when an existing companion is open and unreviewed.

    The merge queue can merge an OPEN companion (it sequences ts-mono
    first), but a substantive viewer change should pass ts-mono's own
    review before queueing — merged or APPROVED companions pass. No
    companion at all passes trivially.
    """
    comp = companion_pr(issue, pr.get("headRefName") or "")
    if comp is None or comp["merged"] or companion_approved(comp):
        return False
    if comp["state"] == "CLOSED":  # closed unmerged: not a blocker, but note it
        actions.append(
            f"#{issue}: note — companion {comp['_repo']}#{comp['number']} closed unmerged"
        )
        return False
    actions.append(
        f"#{issue}: upstream approved but waiting on companion "
        f"{comp['_repo']}#{comp['number']} (open, unreviewed) — holding stage"
    )
    return True


def companion_leftover_warning(issue: int, pr) -> None:
    """Warn about a companion left open after the upstream merge.

    CI forces the companion onto ts-mono main before upstream can merge,
    so an OPEN companion here is a leftover to close by hand — warn only.
    """
    comp = companion_pr(issue, pr.get("headRefName") or "")
    if comp is not None and comp["state"] == "OPEN":
        actions.append(
            f"#{issue}: WARNING companion {comp['_repo']}#{comp['number']} "
            f"still open after upstream merge — close it manually"
        )


def sync_item(row) -> None:
    pr = upstream_pr(row["url"])
    owner, repo, num = pr["_ref"]
    stage, item, issue = row["stage"], row["item"], row["issue"]

    if pr["merged"]:
        try:
            companion_leftover_warning(issue, pr)
        except Exception as e:  # noqa: BLE001 — warn-only, never blocks Done
            print(f"::warning::companion leftover check failed for #{issue}: {e}")
        close_issue(
            issue, f"Upstream PR {row['url']} was merged — closing. (Atlas sync)"
        )
        clear_field(item, STAGE_FIELD)
        set_single_select(item, STATUS_FIELD, STATUS_OPTIONS["Done"])
        actions.append(f"#{issue}: upstream merged -> closed (Done)")
        return

    if pr["state"] == "CLOSED":  # closed without merge
        if row["external"]:
            close_issue(
                issue,
                f"Upstream PR {row['url']} was closed unmerged — closing. (Atlas sync)",
            )
            clear_field(item, STAGE_FIELD)
            set_single_select(item, STATUS_FIELD, STATUS_OPTIONS["Done"])
            actions.append(f"#{issue}: upstream closed -> proxy closed")
        elif stage in TAIL_STAGES and set_stage(item, "Review", stage):
            # Gated to the tail so a stage the driver parked elsewhere is left
            # alone — and the comment can't be re-posted on an hourly bounce.
            comment(
                issue,
                f"Upstream PR {row['url']} was closed unmerged — needs a human decision. (Atlas sync)",
            )
            actions.append(f"#{issue}: upstream closed unmerged -> Review")
        return

    # True re-request: pending request(s) AND the latest request event is newer
    # than the latest changes-requested review (see upstream_pr). A stale
    # never-consumed request from a second reviewer does NOT count — treating
    # it as one would yank human-parked items hourly.
    pending_request = any(
        (n.get("requestedReviewer") or {}).get("login")
        for n in pr["reviewRequests"]["nodes"]
    )
    rerequested = (
        pending_request
        and pr["_req_ts"] > pr["_changes_ts"]
        and pr["_changes_ts"] != ""
    )
    decision = pr.get("reviewDecision")

    if row["external"]:
        if decision == "APPROVED":
            # Maintainer approval hands the external PR to the merge queue
            # (the merge-approved-prs skill drives Merge-stage items home).
            # APPROVED is sticky, so this holds the proxy in Merge each hour —
            # deliberate: to pull a queued external back, dismiss the approval
            # or request changes upstream, not just move the card.
            if stage != "Merge" and companion_blocks_merge(issue, pr):
                return
            if set_stage(item, "Merge", stage):
                actions.append(f"#{issue}: upstream approved -> Merge")
            return
        if stage == "Merge":
            # Was queued but the approval no longer stands (dismissed, or a
            # changes-requested round started) — back to Review: the ball is
            # with the maintainer to re-decide, not with the contributor.
            if set_stage(item, "Review", stage):
                actions.append(f"#{issue}: approval no longer stands -> Review")
            return
        if stage == "Contributor":
            author_ts, reviewer_ts = latest_activity(owner, repo, num)
            # Same staleness rule, against MY last activity: only a request to
            # me newer than my last review/comment pulls the proxy back — my
            # own never-consumed initial request must not.
            rerequested_to_me = (
                any(
                    (n.get("requestedReviewer") or {}).get("login") == REVIEWER
                    for n in pr["reviewRequests"]["nodes"]
                )
                and pr["_req_ts"] > reviewer_ts
            )
            if (author_ts and author_ts > reviewer_ts) or rerequested_to_me:
                if set_stage(item, "Review", stage):
                    actions.append(f"#{issue}: contributor responded -> Review")
        return

    # The one transition allowed OUT of Review: the driver re-requested
    # review upstream after a changes-requested round — the fork's analog of
    # "you send it to a second reviewer", i.e. Review -> Sign-off. The
    # signal is precise (sticky CHANGES_REQUESTED + a pending re-request), so
    # a fresh promotion parked in Review (decision REVIEW_REQUIRED)
    # stays parked.
    if stage == "Review" and decision == "CHANGES_REQUESTED" and rerequested:
        if set_stage(item, "Sign-off", stage):
            actions.append(f"#{issue}: review re-requested upstream -> Sign-off")
        return

    # Promotion tail — only while the ball is genuinely upstream. Stages a
    # human parked elsewhere (Agent, Review, ...) are out of this
    # mapping's domain: reviewDecision is sticky (CHANGES_REQUESTED persists
    # until a re-review), so acting from any stage would drag parked items back
    # here every hour.
    if stage not in TAIL_STAGES:
        return
    if decision == "CHANGES_REQUESTED" and rerequested:
        # Stale: fixes were pushed and a re-review requested; the recorded
        # decision persists until the reviewer acts. Treat as review-pending.
        decision = None
    if decision == "APPROVED":
        if stage != "Merge" and companion_blocks_merge(issue, pr):
            return
        if set_stage(item, "Merge", stage):
            actions.append(f"#{issue}: upstream approved -> Merge")
    elif decision == "CHANGES_REQUESTED":
        if set_stage(item, "Review", stage):
            actions.append(f"#{issue}: upstream changes requested -> Review")
    else:  # REVIEW_REQUIRED / None: only undo a stale Merge
        if stage == "Merge" and set_stage(item, "Sign-off", stage):
            actions.append(f"#{issue}: approval dismissed -> Sign-off")


def lifecycle_item(issue: int):
    """The Atlas item + current Stage for a fork issue, or None.

    Pilot-scoped like the rest of the sync: only open issues assigned to
    REVIEWER, and only their item on THIS project.
    """
    d = gql(
        """query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){
             issue(number:$n){ state assignees(first:10){nodes{login}}
               projectItems(first:10){nodes{id project{id}
                 fieldValueByName(name:"Stage"){
                   ... on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}""",
        o=FORK.split("/")[0],
        r=FORK.split("/")[1],
        n=issue,
    )["repository"]["issue"]
    if d is None or d["state"] != "OPEN":
        return None
    if REVIEWER not in [a["login"] for a in d["assignees"]["nodes"]]:
        return None
    for node in d["projectItems"]["nodes"]:
        if node["project"]["id"] == PROJECT_ID:
            fv = node.get("fieldValueByName") or {}
            return (node["id"], fv.get("name"))
    return None


def reflect_companion_loops() -> None:
    """Reflect companion auto-loops onto their anchors' lifecycle stage.

    An auto-labeled ts-mono PR named by the dev-agent convention
    (claude/issue-N-*) is the active half of fork issue N. The loop's
    ending contract makes ball ownership readable from marker comments:
    a round ends with exactly one of a continue signal (a bare re-review
    trigger comment, or a `claude-review-verdict:suggestions` marker) or
    a stop signal (`auto-handoff` / `auto-converged` /
    `claude-review-verdict:clean`). Newer continue than stop -> the
    machinery owns the issue (Agent); otherwise a human does (Review).
    Only items already in Agent/Review move — parked stages are left
    alone, same as the promotion tail.
    """
    try:
        prs = gh_json(
            "pr",
            "list",
            "--repo",
            TS_MONO,
            "--label",
            "auto",
            "--state",
            "open",
            "--json",
            "number,headRefName",
        )
    except RuntimeError as e:
        print(f"::warning::companion reflection: pr list failed: {e}")
        return
    for cpr in prs:
        m = re.match(r"claude/issue-(\d+)-", cpr.get("headRefName") or "")
        if not m:
            continue
        n = int(m.group(1))
        anchor = lifecycle_item(n)
        if anchor is None:
            continue
        item, stage = anchor
        if stage not in ("Agent", "Review"):
            continue
        comments = gh_json(
            "api",
            "--paginate",
            f"repos/{TS_MONO}/issues/{cpr['number']}/comments?per_page=100",
            "--jq",
            "[.[] | {body: .body, ts: .created_at}]",
        )
        # --paginate concatenates arrays as JSON streams only for objects;
        # normalize: gh emits one array per page back-to-back
        if isinstance(comments, dict):
            comments = [comments]
        go_ts, stop_ts = "", ""
        for c in comments if isinstance(comments, list) else []:
            body, ts = c.get("body") or "", c.get("ts") or ""
            if (
                "auto-handoff" in body
                or "auto-converged" in body
                or "claude-review-verdict:clean" in body
            ):
                stop_ts = max(stop_ts, ts)
            elif (
                body.strip() == "@" + "review"
                or "claude-review-verdict:suggestions" in body
            ):
                go_ts = max(go_ts, ts)
        engaged = go_ts > stop_ts
        target = "Agent" if engaged else "Review"
        if set_stage(item, target, stage):
            state = "engaged" if engaged else "handed back"
            actions.append(
                f"#{n}: companion {TS_MONO}#{cpr['number']} loop {state} -> {target}"
            )


def main() -> int:
    discover()
    for row in board_items():
        try:
            sync_item(row)
        except Exception as e:  # noqa: BLE001 — per-item isolation
            print(f"::warning::sync failed for #{row['issue']}: {e}")
    try:
        reflect_companion_loops()
    except Exception as e:  # noqa: BLE001 — reflection must not break the sync
        print(f"::warning::companion reflection failed: {e}")

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
