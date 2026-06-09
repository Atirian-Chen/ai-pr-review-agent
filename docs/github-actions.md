# GitHub Actions Auto Review

The workflow in `.github/workflows/ai-review.yml` runs AI review automatically.

## Triggers

- `push`: reviews the pushed commit range as a GitHub compare target and comments the summary on the head commit.
- `pull_request`: reviews the PR and creates or updates one summary comment on the PR conversation.

## Required Secrets

```text
OPENAI_API_KEY
VERIFIER_OPENAI_API_KEY
```

`OPENAI_API_KEY` is used by the primary review model. `VERIFIER_OPENAI_API_KEY` is used by the optional second-pass verifier model. If `VERIFIER_OPENAI_API_KEY` is not configured, the deterministic verifier still runs and the LLM verifier is marked as skipped.

The workflow passes GitHub's built-in token as `GITHUB_TOKEN`.

## Model Environment Variables

Primary reviewer:

```yaml
OPENAI_BASE_URL: https://api.deepseek.com
OPENAI_MODEL: deepseek-v4-pro
OPENAI_TIMEOUT_SECONDS: "500"
```

LLM verifier:

```yaml
VERIFIER_OPENAI_BASE_URL: https://api.deepseek.com
VERIFIER_OPENAI_MODEL: deepseek-chat
VERIFIER_OPENAI_TIMEOUT_SECONDS: "120"
```

The primary model can be a stronger reasoning model. The verifier model is intended to be cheaper and faster, such as a mini, flash, or chat model.

## Permissions

- `contents: write`: required for commit comments on push events.
- `issues: write`: required for PR conversation comments.
- `pull-requests: write`: required to read PR metadata and publish PR summary comments.

## Local Dry Run

```powershell
pr-agent review-action --event-path path/to/event.json --event-name pull_request --dry-run
```

The dry run writes:

- `review_result.json`
- `review_report.md`
- `trace.jsonl`
- `github_action_target.json`
- `summary_comment.md`
