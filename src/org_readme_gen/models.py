from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RepoInfo:
    name: str
    description: str
    url: str
    language: str
    stars: int
    topics: list[str]
    fork: bool
    archived: bool
    readme_excerpt: str = ""
    # 未提供可见性时按私有处理，避免旧调用方或不完整 API 响应把内部信息带到公开主页。
    private: bool = True


@dataclass(slots=True)
class OrgConfig:
    name: str
    audience: str = "public"
    description: str = ""
    extra_instructions: str = ""
    output_branch: str = "main"


@dataclass(slots=True)
class LlmConfig:
    provider: str = "openai"
    model: str = "deepseek-chat"
    base_url: str = ""
    api_key_env: str = "LLM_API_KEY"
    max_tokens: int = 8192


@dataclass(slots=True)
class AppConfig:
    llm: LlmConfig = field(default_factory=LlmConfig)
    orgs: list[OrgConfig] = field(default_factory=list)
