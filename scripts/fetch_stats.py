"""Fetch live GitHub numbers for the card and save them to profile/stats.json.

Needs a token in the GH_TOKEN environment variable (the GitHub Action passes one).
  - With the default Actions token: counts your PUBLIC repos only.
  - With a personal token saved as the repo secret ACCESS_TOKEN: private repos count too.

Numbers:
  repos        repos you own
  contributed  repos you committed to / opened PRs in (yours included)
  stars        stars on repos you own
  followers    people following you
  commits      your commits on the default branch of every repo you can see
  loc_*        lines added / deleted in those commits
  languages    top languages by code size in repos you own (forks skipped)
  contrib      total contributions, streaks and the last 52 weeks
"""

import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com/graphql"

USER_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    id
    createdAt
    followers { totalCount }
    repositoriesContributedTo(first: 1, includeUserRepositories: true,
                              contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) { totalCount }
    repositories(first: 100, after: $cursor,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name stargazerCount isFork owner { login }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

HISTORY_QUERY = """
query($owner: String!, $name: String!, $uid: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef { target { ... on Commit {
      history(first: 100, after: $cursor, author: {id: $uid}) {
        totalCount
        pageInfo { hasNextPage endCursor }
        nodes { additions deletions }
      }
    } } }
  }
}
"""


CALENDAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}
"""


def gql(query: str, **variables) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    headers = {
        "Authorization": f"bearer {os.environ['GH_TOKEN']}",
        "Content-Type": "application/json",
        "User-Agent": "profile-card-updater",
    }
    for attempt in range(5):
        try:
            req = urllib.request.Request(API, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as err:
            # GitHub sometimes times out on big commit pages: wait and retry.
            if err.code in (502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        return data["data"]
    raise RuntimeError("GitHub API kept failing")


def repo_commits(owner: str, name: str, uid: str) -> tuple[int, int, int]:
    """(commits, lines added, lines deleted) by this user on the default branch."""
    commits = added = deleted = 0
    cursor = None
    while True:
        repo = gql(HISTORY_QUERY, owner=owner, name=name, uid=uid, cursor=cursor)["repository"]
        branch = repo and repo["defaultBranchRef"]
        if not branch:  # empty repo
            return 0, 0, 0
        history = branch["target"]["history"]
        commits = history["totalCount"]
        for node in history["nodes"]:
            added += node["additions"]
            deleted += node["deletions"]
        if not history["pageInfo"]["hasNextPage"]:
            return commits, added, deleted
        cursor = history["pageInfo"]["endCursor"]


def top_languages(owned: list, exclude: list[str], keep: int = 6) -> list[dict]:
    """Share of code (by bytes) per language, biggest first. Extra ones become "Other"."""
    sizes, colors = {}, {}
    for repo in owned:
        if repo["isFork"]:
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in exclude:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    ranked = sorted(sizes.items(), key=lambda kv: -kv[1])
    langs = [{"name": n, "color": colors[n], "pct": round(100 * s / total, 1)} for n, s in ranked]
    if len(langs) > keep:
        rest = round(100 - sum(lang["pct"] for lang in langs[: keep - 1]), 1)
        langs = langs[: keep - 1] + [{"name": "Other", "color": "#8b949e", "pct": rest}]
    return langs


def contributions(login: str, created_at: str) -> dict:
    """Daily contribution counts since joining -> totals, streaks, last 52 weeks."""
    days: dict[str, int] = {}
    start = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    while start < now:  # the API allows at most one year per request
        end = min(start + timedelta(days=365), now)
        data = gql(CALENDAR_QUERY, login=login, **{"from": start.isoformat(), "to": end.isoformat()})
        for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                days[day["date"]] = day["contributionCount"]
        start = end

    dates = sorted(days)
    counts = [days[d] for d in dates]

    # Longest run of days with at least one contribution.
    longest = (0, None, None)
    run_start = None
    for i, c in enumerate(counts):
        if c and run_start is None:
            run_start = i
        if run_start is not None and (not c or i == len(counts) - 1):
            run_end = i if c else i - 1
            if run_end - run_start + 1 > longest[0]:
                longest = (run_end - run_start + 1, dates[run_start], dates[run_end])
            run_start = None

    # Current streak: count back from today (today may still be empty).
    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:
        i -= 1
    end_i = i
    while i >= 0 and counts[i]:
        i -= 1
    current = end_i - i

    today = date.fromisoformat(dates[-1])
    last_year = counts[-364:]
    return {
        "total": sum(counts),
        "this_year": sum(c for d, c in zip(dates, counts) if d.startswith(str(today.year))),
        "since": dates[0],
        "current_streak": current,
        "current_start": dates[i + 1] if current else None,
        "current_end": dates[end_i] if current else None,
        "longest_streak": longest[0],
        "longest_start": longest[1],
        "longest_end": longest[2],
        "weeks": [sum(last_year[w : w + 7]) for w in range(0, len(last_year), 7)],
    }


def main() -> None:
    if not os.environ.get("GH_TOKEN"):
        print("GH_TOKEN not set: keeping the old profile/stats.json")
        return
    cfg = tomllib.loads((ROOT / "profile" / "config.toml").read_text(encoding="utf-8"))
    login = cfg["username"]

    repos, cursor = [], None
    while True:
        user = gql(USER_QUERY, login=login, cursor=cursor)["user"]
        page = user["repositories"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    owned = [r for r in repos if r["owner"]["login"].lower() == login.lower()]
    stats = {
        "repos": len(owned),
        "contributed": user["repositoriesContributedTo"]["totalCount"],
        "stars": sum(r["stargazerCount"] for r in owned),
        "followers": user["followers"]["totalCount"],
        "commits": 0,
        "loc_add": 0,
        "loc_del": 0,
    }
    for r in repos:
        try:
            c, a, d = repo_commits(r["owner"]["login"], r["name"], user["id"])
        except Exception as err:  # one broken repo should not stop the whole card
            print(f"warning: skipped {r['owner']['login']}/{r['name']}: {err}", file=sys.stderr)
            continue
        stats["commits"] += c
        stats["loc_add"] += a
        stats["loc_del"] += d
    stats["loc_total"] = stats["loc_add"] - stats["loc_del"]
    stats["languages"] = top_languages(owned, cfg.get("exclude_languages", []))
    stats["contrib"] = contributions(login, user["createdAt"])
    stats["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    (ROOT / "profile" / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
