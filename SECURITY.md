# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| latest release on `main` | ✅ |
| older releases | best effort |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Open a [GitHub Security Advisory](https://github.com/xkx121029/HappyClaw/security/advisories/new)
on this repository. It is the only reporting channel: it keeps the report private
between you and the maintainers, and it threads the fix and the disclosure in one
place. Do not email individuals about a vulnerability.

We aim to acknowledge reports within **3 business days** and provide a fix timeline within **7 business days** for confirmed issues.

## Scope

HappyClaw is a single-user workspace bound to the local owner. There is no
login, JWT secret, or administrator password to rotate. You are responsible for:

- Securing the host and network exposure of `octop run`
- Protecting `~/.octop/` — the database, `config.json`, `env`, and `secrets/`
- Reviewing tool guard rules under `~/.octop/security/tool_guard/`
- Protecting LLM API keys and IM channel credentials

See [docs/configuration.md](docs/configuration.md) for deployment hardening guidance.
