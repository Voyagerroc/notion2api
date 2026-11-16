# Security policy

This is an experimental unofficial Notion web integration. Fixes target the latest `main` and current preview release. No production suitability, response deadline, bounty or legal compliance is promised.

Report vulnerabilities privately through [GitHub private reporting](https://github.com/Voyagerroc/notion2api/security/advisories/new), or contact **erol@voyagerroctechnologies.com** if unavailable. Include a minimal synthetic reproduction and impact; never send session tokens, passwords, real prompts or personal workspace data in public issues.

Credentials are local files, not an encrypted vault. Restrict OS access, exclude the state directory from inappropriate sharing/backups, and revoke compromised sessions through Notion. `logout` removes local saved credentials; it does not revoke remote sessions or erase every conversation database. Explicit `NOTION2API_HOME` selects isolated state. A source checkout preserves its existing credential location; installed wheels use a per-user directory.

Prompts and selected files leave the machine for the configured upstream. `NOTION_URL` can override the default Notion host; verify configuration before sending context. Models, availability, cost and quotas depend on the service/account. Offline tests do not establish live provider access or compliance with provider terms.

The packaged server launcher binds only loopback. Raw Uvicorn/deployment entry points remain configurable; do not expose them without authentication, restrictive CORS, TLS and an operational review. Agent/patching features are not an OS sandbox: syntax validation does not prove generated code safe or correct. Review patches and use disposable workspaces.
