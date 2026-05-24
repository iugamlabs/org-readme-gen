from __future__ import annotations

from pathlib import Path

import yaml

from org_readme_gen.models import AppConfig, LlmConfig, OrgConfig

_CONFIG_SEARCH_PATHS = [
    Path("config.yaml"),
    Path.home() / ".config" / "org-readme-gen" / "config.yaml",
]


def find_config(explicit: Path | None = None) -> Path:
    if explicit is not None:
        if not explicit.exists():
            raise FileNotFoundError(f"配置文件不存在: {explicit}")
        return explicit

    for path in _CONFIG_SEARCH_PATHS:
        if path.exists():
            return path

    raise FileNotFoundError(
        "未找到配置文件，请通过 --config 指定，或在当前目录创建 config.yaml"
    )


def load_config(path: Path) -> AppConfig:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    llm_raw = raw.get("llm", {})
    llm = LlmConfig(
        provider=llm_raw.get("provider", "openai"),
        model=llm_raw.get("model", "deepseek-chat"),
        base_url=llm_raw.get("base_url", ""),
        api_key_env=llm_raw.get("api_key_env", "LLM_API_KEY"),
        max_tokens=llm_raw.get("max_tokens", 8192),
    )

    orgs: list[OrgConfig] = []
    for org_raw in raw.get("orgs", []):
        orgs.append(
            OrgConfig(
                name=org_raw["name"],
                audience=org_raw.get("audience", "public"),
                description=org_raw.get("description", ""),
                extra_instructions=org_raw.get("extra_instructions", ""),
                output_branch=org_raw.get("output_branch", "main"),
            )
        )

    return AppConfig(llm=llm, orgs=orgs)
