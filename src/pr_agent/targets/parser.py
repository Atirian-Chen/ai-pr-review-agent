"""Target parser：根据用户输入自动识别 PR、commit、compare 或本地 diff。"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

from pr_agent.targets.models import ReviewTargetRef


def parse_review_target(target: str) -> ReviewTargetRef:
    raw = target.strip()
    if raw.lower() in {"local", "local:working", "local:worktree"}:
        return ReviewTargetRef(source_type="local_diff")

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() != "github.com":
        raise ValueError(
            "Unsupported review target. Use a GitHub PR URL, commit URL, compare URL, or 'local'."
        )

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) >= 4 and parts[2] == "pull" and parts[3].isdigit():
        return ReviewTargetRef(
            source_type="pull_request",
            owner=parts[0],
            repo=parts[1],
            pull_number=int(parts[3]),
            url=raw,
        )

    if len(parts) >= 4 and parts[2] == "commit" and parts[3]:
        return ReviewTargetRef(
            source_type="commit",
            owner=parts[0],
            repo=parts[1],
            commit_sha=parts[3],
            url=raw,
        )

    if len(parts) >= 4 and parts[2] == "compare":
        compare_spec = "/".join(parts[3:])
        separator = "..." if "..." in compare_spec else ".." if ".." in compare_spec else None
        if separator is None:
            raise ValueError(f"Invalid GitHub compare URL: {target}")
        base_ref, head_ref = compare_spec.split(separator, 1)
        if not base_ref or not head_ref:
            raise ValueError(f"Invalid GitHub compare URL: {target}")
        return ReviewTargetRef(
            source_type="compare",
            owner=parts[0],
            repo=parts[1],
            base_ref=base_ref,
            head_ref=head_ref,
            url=raw,
        )

    raise ValueError(f"Unsupported GitHub review target: {target}")
