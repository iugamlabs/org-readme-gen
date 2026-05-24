from __future__ import annotations

import os
from collections.abc import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from org_readme_gen.models import LlmConfig, OrgConfig, RepoInfo

console = Console()

_SYSTEM_PROMPT_TEMPLATE = """\
你是一个技术文档专家。你的任务是为 GitHub 组织生成一个精美的主页 README.md。

## 输出要求
- 输出纯 Markdown，不要包裹在代码块中
- 使用中文撰写（除非组织描述是英文）
- 根据受众类型（{audience}）调整语气和内容深度
- 包含以下部分：
  1. 组织标题和一句话定位
  2. Mermaid 架构/关系图（如果项目间有关系）
  3. 项目总览表格（名称、说明、语言、Stars）
  4. 各项目详情（简要说明核心功能和技术要点）
  5. 技术栈概览
- Mermaid 图表要有颜色区分，使用 style 命令
- 排除 fork 仓库和已归档仓库，除非它们是组织的核心项目
- 保持简洁，不要过度装饰

## 受众说明
- public：面向外部用户和开源社区，强调产品价值和使用方式
- internal：面向团队内部成员，强调技术架构和项目状态，可包含内部约定

## 格式规范
- 标题用 # ，各部分用 ##
- 表格用 | 分隔
- Mermaid 图用 ```mermaid 包裹
- 链接用 [text](url) 格式
"""


def _build_system_prompt(audience: str) -> str:
    return _SYSTEM_PROMPT_TEMPLATE.format(audience=audience)


def _build_user_prompt(
    org_config: OrgConfig,
    repos: list[RepoInfo],
    existing_readme: str | None,
) -> str:
    lines: list[str] = []
    lines.append(f"# 组织信息\n- 名称：{org_config.name}")
    if org_config.description:
        lines.append(f"- 描述：{org_config.description}")
    lines.append(f"- 受众：{org_config.audience}")

    if org_config.extra_instructions:
        lines.append(f"\n# 额外指示\n{org_config.extra_instructions}")

    lines.append("\n# 仓库列表")
    for repo in repos:
        status_parts: list[str] = []
        if repo.fork:
            status_parts.append("fork")
        if repo.archived:
            status_parts.append("已归档")
        status = f" [{', '.join(status_parts)}]" if status_parts else ""

        topic_str = ", ".join(repo.topics) if repo.topics else ""
        lines.append(
            f"\n## {repo.name}{status}\n"
            f"- 描述：{repo.description or '（无描述）'}\n"
            f"- 语言：{repo.language or '未知'}\n"
            f"- Stars：{repo.stars}\n"
            f"- 链接：{repo.url}\n"
            f"- Topics：{topic_str or '无'}"
        )
        if repo.readme_excerpt:
            lines.append(f"- README 摘要：\n{repo.readme_excerpt}")

    if existing_readme:
        lines.append(f"\n# 当前 README（供参考改进）\n{existing_readme}")

    return "\n".join(lines)


def _stream_openai(config: LlmConfig, system: str, user: str) -> Iterator[str]:
    from openai import OpenAI

    api_key = os.environ.get(config.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"请设置 {config.api_key_env} 环境变量")

    client = OpenAI(base_url=config.base_url or None, api_key=api_key)
    stream = client.chat.completions.create(
        model=config.model,
        max_tokens=config.max_tokens,
        stream=True,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def _stream_anthropic(config: LlmConfig, system: str, user: str) -> Iterator[str]:
    import anthropic

    api_key = os.environ.get(config.api_key_env, "")
    if not api_key:
        raise RuntimeError(f"请设置 {config.api_key_env} 环境变量")

    client = anthropic.Anthropic(api_key=api_key)
    with client.messages.stream(
        model=config.model,
        max_tokens=config.max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def generate_readme(
    llm_config: LlmConfig,
    org_config: OrgConfig,
    repos: list[RepoInfo],
    existing_readme: str | None,
) -> str:
    system = _build_system_prompt(org_config.audience)
    user = _build_user_prompt(org_config, repos, existing_readme)

    console.print(f"  调用 LLM（{llm_config.provider}/{llm_config.model}）生成 README ...")

    if llm_config.provider == "anthropic":
        stream_iter = _stream_anthropic(llm_config, system, user)
    else:
        stream_iter = _stream_openai(llm_config, system, user)

    content = ""
    _TAIL_CHARS = 2000
    with Live(
        Panel(Markdown(""), title="LLM 生成中", border_style="cyan"),
        console=console,
        refresh_per_second=8,
    ) as live:
        for chunk in stream_iter:
            content += chunk
            tail = content[-_TAIL_CHARS:]
            if len(content) > _TAIL_CHARS:
                tail = "…" + tail
            live.update(Panel(Markdown(tail), title="LLM 生成中", border_style="cyan"))

    return content
