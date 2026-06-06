# GitHub Actions Auto Review

The workflow in `.github/workflows/ai-review.yml` runs AI review automatically.

## Triggers

- `push`: reviews the pushed commit range as a GitHub compare target and comments the summary on the head commit.
- `pull_request`: reviews the PR and creates or updates one summary comment on the PR conversation.

## Required Secret

```text
OPENAI_API_KEY
```

The workflow passes GitHub's built-in token as `GITHUB_TOKEN`.

## Permissions

- `contents: write`: required for commit comments on push events.
- `issues: write`: required for PR conversation comments.
- `pull-requests: read`: required to read PR metadata.

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
