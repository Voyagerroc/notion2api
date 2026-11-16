# Contributing

Use Python 3.10+ and Git. Install uv 0.12.5, then run:

```console
uv sync --locked --extra dev
uv run --locked --extra dev ruff check .
uv run --locked --extra dev pytest tests/ -q
uv build --wheel
```

The suite uses synthetic account data, temporary state and mocked upstream calls. It must not read an operator's credentials or contact Notion. New network behavior needs mocks and meaningful failure checks. CLI help must work without an account, even outside the checkout.

Keep one problem per PR, explain resulting behavior and actual validation, and disclose unavailable checks. Tests and source use the same explicitly configured basic Ruff rules; passing lint is not a security audit. Update `uv.lock` deliberately when changing dependencies; review the diff and rerun both operating-system checks. Do not refresh dependencies as a side effect of unrelated work.

Never include `.env`, `accounts.json`, databases, prompts, personal workspace IDs or response logs. Report vulnerabilities privately through [SECURITY.md](SECURITY.md). The project uses the existing MIT license.
