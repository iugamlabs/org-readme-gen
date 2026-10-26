# org-readme-gen

使用 LLM 自动生成和更新 GitHub 组织主页 README。

## 功能

- 自动获取 GitHub 组织下的所有仓库信息（Stars、Topics、语言、描述）
- 对无描述的仓库自动提取 README 摘要作为上下文
- 调用 LLM 生成精美的组织主页 README（含 Mermaid 图表、表格、分类）
- 支持 OpenAI 兼容 API（DeepSeek、Ollama、vLLM 等）和 Anthropic Claude
- 支持 dry-run 预览和指定 org 过滤

## 安装

```bash
# 从源码安装
git clone https://github.com/your-org/org-readme-gen.git
cd org-readme-gen
uv sync
uv pip install -e .
```

## 配置

复制示例配置文件：

```bash
cp config.example.yaml config.yaml
```

编辑 `config.yaml`，配置 LLM 和组织信息：

```yaml
llm:
  provider: "openai"                 # openai | anthropic
  model: "deepseek-chat"
  base_url: "https://api.deepseek.com/v1"
  api_key_env: "LLM_API_KEY"
  max_tokens: 8192

orgs:
  - name: "your-org"
    audience: "public"
    description: "你的组织描述"
    output_branch: "main"
```

设置环境变量（支持 `.env` 文件或 shell export）：

```bash
# 方式一：创建 .env 文件（推荐）
cp .env.example .env
# 编辑 .env 填入你的密钥

# 方式二：shell export
export GITHUB_TOKEN="your-github-token"
export LLM_API_KEY="your-llm-api-key"
```

## 使用

```bash
# 生成并推送所有 org 的 README
org-readme-gen update

# 只处理指定 org
org-readme-gen update --org iugamlabs

# 只生成不推送（预览）
org-readme-gen update --dry-run

# 指定配置文件
org-readme-gen update --config ./my-config.yaml
```

## 环境变量

| 变量 | 说明 |
|------|------|
| `GITHUB_TOKEN` | GitHub Personal Access Token（需要 `repo` 和 `admin:org` 权限） |
| `LLM_API_KEY` | LLM API Key（可通过配置文件 `api_key_env` 自定义变量名） |

## 公开与内部主页

`audience: public` 只把公开项目的元数据与摘要交给 LLM，读写 `.github`；`audience: internal` 可包含内部项目，读写私有的 `.github-private`。内容与 SHA 从 `output_branch` 的同一目标读取，不会跨仓库回退。`--dry-run` 不创建仓库或写入文件。

受众必须是 `public` 或 `internal`。新建内部主页仓库会显式设为私有；现有目标若是公开仓库则拒绝写入。

```bash
uv run --group dev python -m unittest discover -s tests -v
```
