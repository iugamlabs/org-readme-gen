from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from org_readme_gen.config import find_config, load_config
from org_readme_gen.github import (
    ensure_github_repo,
    get_org_readme,
    get_org_repos,
    get_repo_readme,
    update_readme,
)
from org_readme_gen.llm import generate_readme
from org_readme_gen.models import OrgConfig

app = typer.Typer(
    name="org-readme-gen",
    help="使用 LLM 自动生成和更新 GitHub 组织主页 README",
)
console = Console()

_README_EXCERPT_LINES = 30
_README_MESSAGE = "docs: 使用 org-readme-gen 更新组织主页 README"


def _enrich_repos(org: str, repos: list) -> None:
    """为没有描述的仓库提取 README 摘要。"""
    for repo in repos:
        if repo.description:
            continue
        console.print(f"  获取 {repo.name} 的 README ...")
        readme = get_repo_readme(org, repo.name)
        if readme:
            lines = readme.strip().splitlines()
            repo.readme_excerpt = "\n".join(lines[:_README_EXCERPT_LINES])


def _process_org(org_config: OrgConfig, llm_config, dry_run: bool) -> None:
    console.print(Panel(f"[bold cyan]{org_config.name}[/]", subtitle=org_config.audience))

    # 1. 获取仓库列表
    console.print("  获取仓库列表 ...")
    repos = get_org_repos(org_config.name)
    active = [r for r in repos if not r.fork and not r.archived]
    console.print(f"  共 {len(repos)} 个仓库，{len(active)} 个活跃仓库")

    # 2. 补充无描述仓库的 README 摘要
    _enrich_repos(org_config.name, active)

    # 3. 获取现有 README
    existing = get_org_readme(org_config.name)
    existing_content = existing[0] if existing else None
    existing_sha = existing[1] if existing else None
    if existing_content:
        console.print("  已获取现有 README")

    # 4. 调用 LLM 生成
    content = generate_readme(llm_config, org_config, active, existing_content)

    # 5. 输出或推送
    if dry_run:
        console.print("\n[bold green]--- 生成的 README ---[/]\n")
        console.print(Markdown(content))
        console.print(f"\n[dim]（dry-run 模式，未推送到 GitHub）[/]")
    else:
        ensure_github_repo(org_config.name, ".github")
        commit_url = update_readme(
            org=org_config.name,
            content=content,
            sha=existing_sha,
            branch=org_config.output_branch,
            message=_README_MESSAGE,
        )
        console.print(f"  [bold green]已更新[/] → {commit_url}")


@app.command()
def update(
    org: str | None = typer.Option(None, "--org", "-o", help="只处理指定的组织"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="只生成不推送"),
    config_path: Path | None = typer.Option(None, "--config", "-c", help="配置文件路径"),
) -> None:
    """生成并更新 GitHub 组织主页 README。"""
    config_file = find_config(config_path)
    console.print(f"配置文件: {config_file}")
    config = load_config(config_file)

    if org:
        org_configs = [o for o in config.orgs if o.name == org]
        if not org_configs:
            console.print(f"[red]未在配置中找到组织: {org}[/]")
            raise typer.Exit(1)
    else:
        org_configs = config.orgs

    for org_config in org_configs:
        _process_org(org_config, config.llm, dry_run)


def main() -> None:
    load_dotenv()
    app()
