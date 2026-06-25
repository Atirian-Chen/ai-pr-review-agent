# Sandbox Security

## Threat Model

Sandbox verification may execute code from the reviewed repository. That code is untrusted, especially for pull requests. The sandbox design therefore prevents the model and the reviewed code from gaining broad shell, network, filesystem, or secret access.

## Model Boundary

The LLM never supplies a raw shell command. It can only suggest verification intent. The system converts approved tools into fixed templates:

```text
python -m pytest -q <approved_test_path>
python -m pytest -q <approved_test_path>::<approved_test_name>
ruff check <approved_paths>
mypy <approved_paths>
```

The policy gate rejects:

- shell metacharacters
- absolute paths
- `..` path traversal
- `.env`, private keys, credentials, and SSH material
- command-looking search terms such as `python -c ...`, `bash -c ...`, `curl ...`, or `docker ...`

## Workspace Handling

The real workspace is not mounted writable. Before Docker execution, the runner copies the repository into a temporary directory and excludes:

- `.git`
- `.env`
- private keys and credential files
- virtual environments
- `node_modules`
- build and dist outputs
- cache directories
- binary/archive files

The temporary copy is deleted when execution finishes.

## Docker Settings

Docker runs with:

```text
--network none
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit 128
--memory 1g
--cpus 1.0
--read-only
--tmpfs /tmp:rw,noexec,nosuid,size=256m
--env PYTHONDONTWRITEBYTECODE=1
--env HOME=/tmp
```

The container does not receive:

- `OPENAI_API_KEY`
- `VERIFIER_OPENAI_API_KEY`
- `GITHUB_TOKEN`
- any host environment by default

## GitHub Actions Policy

`review-action` reads:

```yaml
PR_AGENT_VERIFY_MODE: sandbox
PR_AGENT_VERIFY_MAX_FINDINGS: "3"
PR_AGENT_VERIFY_TIMEOUT_SECONDS: "45"
PR_AGENT_PUBLISH_POLICY: verified_or_high_confidence
```

Fork pull requests are automatically downgraded from `sandbox` to `static`. This avoids executing untrusted fork code in CI by default.

Recommended behavior:

| Event | Verification |
| --- | --- |
| same-repository pull request | static or sandbox |
| fork pull request | static only |
| push | static or sandbox |

## Residual Risk

Docker sandboxing reduces risk but is not a formal security proof. Keep timeouts small, do not pass secrets to containers, and keep fork PRs on static verification unless a maintainer intentionally changes the policy.

