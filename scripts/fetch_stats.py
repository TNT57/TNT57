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
"""

import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com/graphql"

USER_QUERY = """
query($login: String!, $cursor: String) {
  user(login: $login) {
    id
    followers { totalCount }
    repositoriesContributedTo(first: 1, includeUserRepositories: true,
                              contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY]) { totalCount }
    repositories(first: 100, after: $cursor,
                 ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]) {
      pageInfo { hasNextPage endCursor }
      nodes { name stargazerCount owner { login } }
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


def main() -> None:
    if not os.environ.get("GH_TOKEN"):
        print("GH_TOKEN not set: keeping the old profile/stats.json")
        return
    login = tomllib.loads((ROOT / "profile" / "config.toml").read_text(encoding="utf-8"))["username"]

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
    stats["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    (ROOT / "profile" / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
