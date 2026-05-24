from __future__ import annotations

import base64
import os

import httpx
from rich.console import Console

from org_readme_gen.models import RepoInfo

console = Console()

_GRAPHQL_ORG_REPOS = """
query($org: String!, $after: String) {
  organization(login: $org) {
    repositories(first: 100, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        description
        url
        isArchived
        isFork
        primaryLanguage { name }
        repositoryTopics(first: 10) { nodes { topic { name } } }
        stargazerCount
        forkCount
        updatedAt
      }
    }
  }
}
"""


def _get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        import subprocess

        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            token = result.stdout.strip()
    if not token:
        raise RuntimeError(
            "请设置 GITHUB_TOKEN 环境变量，或先运行 gh auth login 登录 GitHub CLI"
        )
    return token


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def get_org_repos(org: str) -> list[RepoInfo]:
    repos: list[RepoInfo] = []
    cursor: str | None = None

    with httpx.Client(timeout=30) as client:
        while True:
            variables: dict[str, object] = {"org": org}
            if cursor:
                variables["after"] = cursor

            resp = client.post(
                "https://api.github.com/graphql",
                headers=_headers(),
                json={"query": _GRAPHQL_ORG_REPOS, "variables": variables},
            )
            resp.raise_for_status()
            data = resp.json()

            if "errors" in data:
                raise RuntimeError(f"GraphQL 错误: {data['errors']}")

            repo_data = data["data"]["organization"]["repositories"]
            for node in repo_data["nodes"]:
                lang = node.get("primaryLanguage")
                topics = [
                    t["topic"]["name"]
                    for t in node.get("repositoryTopics", {}).get("nodes", [])
                ]
                repos.append(
                    RepoInfo(
                        name=node["name"],
                        description=node.get("description") or "",
                        url=node["url"],
                        language=lang["name"] if lang else "",
                        stars=node.get("stargazerCount", 0),
                        topics=topics,
                        fork=node.get("isFork", False),
                        archived=node.get("isArchived", False),
                    )
                )

            page_info = repo_data["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            cursor = page_info["endCursor"]

    return repos


def get_repo_readme(org: str, repo: str) -> str | None:
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"https://api.github.com/repos/{org}/{repo}/readme",
            headers={**_headers(), "Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        content = resp.json().get("content", "")
        return base64.b64decode(content).decode("utf-8") if content else None


def get_org_readme(org: str) -> tuple[str, str] | None:
    """返回 (内容, SHA)，如不存在返回 None。"""
    with httpx.Client(timeout=30) as client:
        # 尝试 .github-private（如 star-plan），再尝试 .github
        for repo_name in [f"{org}/.github-private", f"{org}/.github"]:
            resp = client.get(
                f"https://api.github.com/repos/{repo_name}/contents/profile/README.md",
                headers={**_headers(), "Accept": "application/vnd.github.v3+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return content, data["sha"]
        return None


def get_default_branch(org: str, repo: str) -> str:
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"https://api.github.com/repos/{org}/{repo}",
            headers={**_headers(), "Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code == 404:
            return "main"
        resp.raise_for_status()
        return resp.json().get("default_branch", "main")


def ensure_github_repo(org: str, repo: str) -> None:
    """确保 .github 仓库存在，不存在则创建。"""
    with httpx.Client(timeout=30) as client:
        resp = client.get(
            f"https://api.github.com/repos/{org}/{repo}",
            headers={**_headers(), "Accept": "application/vnd.github.v3+json"},
        )
        if resp.status_code == 200:
            return
        if resp.status_code != 404:
            resp.raise_for_status()

        console.print(f"  创建仓库 {org}/{repo} ...")
        resp = client.post(
            "https://api.github.com/orgs/{}/repos".format(org),
            headers=_headers(),
            json={"name": repo, "description": f"{org} org profile", "auto_init": True},
        )
        resp.raise_for_status()


def update_readme(
    org: str,
    content: str,
    sha: str | None,
    branch: str,
    message: str,
) -> str:
    """更新 profile README，返回 commit URL。"""
    # 确定使用 .github 还是 .github-private
    repo_name = f"{org}/.github"

    with httpx.Client(timeout=30) as client:
        # 检查文件是否存在
        if sha is None:
            resp = client.get(
                f"https://api.github.com/repos/{repo_name}/contents/profile/README.md",
                headers={**_headers(), "Accept": "application/vnd.github.v3+json"},
                params={"ref": branch},
            )
            if resp.status_code == 200:
                sha = resp.json()["sha"]

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        body: dict[str, object] = {
            "message": message,
            "content": encoded,
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        resp = client.put(
            f"https://api.github.com/repos/{repo_name}/contents/profile/README.md",
            headers=_headers(),
            json=body,
        )
        resp.raise_for_status()
        return resp.json().get("commit", {}).get("html_url", "")
