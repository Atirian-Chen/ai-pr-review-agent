# AI PR Review Agent

AI PR Review Agent is an MVP for local GitHub Pull Request review:

- fetch PR metadata and changed files through the GitHub REST API
- parse GitHub patch text into structured diff hunks
- retrieve lightweight repository context
- call an OpenAI-compatible LLM for conservative, structured findings
- validate findings and render JSON plus Markdown reports

## Quick Start

```powershell
python -m venv .venv
.\.venv\bin\python -m pip install -e ".[dev]"
copy .env.example .env
```

If your Python creates a Windows-style virtual environment, replace `.\.venv\bin\python` with `.\.venv\Scripts\python`.

On this workspace, the default MSYS Python cannot install `pydantic-core` wheels cleanly. Use the Codex bundled Windows Python environment instead:

```powershell
C:\Users\Atirian\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-win\Scripts\python.exe -m pytest
```

Fill `.env` or set environment variables:

```powershell
$env:GITHUB_TOKEN="ghp_xxx"
$env:OPENAI_API_KEY="sk_xxx"
$env:OPENAI_MODEL="gpt-4.1-mini"
```

Fetch PR data only:

```powershell
pr-agent fetch https://github.com/owner/repo/pull/123 --out outputs/demo
```

Run the MVP review:

```powershell
pr-agent review https://github.com/owner/repo/pull/123 --out outputs/demo
```

Outputs:

- `outputs/demo/fetch_result.json`
- `outputs/demo/review_result.json`
- `outputs/demo/review_report.md`
- `outputs/demo/trace.jsonl`

## Notes

The MVP intentionally does not post GitHub comments or run code from the PR. It only reads PR metadata, changed files, and repository content needed for review context.
