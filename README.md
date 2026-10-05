# MDS-Corp

Local tooling for [mdsindustrialcorp.com](https://mdsindustrialcorp.com): WordPress connection, Google Search Console indexing checks, Google Business Profile posting, and a dashboard at http://127.0.0.1:8765/.

Work is **agent-based**: each new job gets its own agent, branch, and worktree so one task cannot break another. See [AGENTS.md](AGENTS.md) and [docs/AGENTS.md](docs/AGENTS.md).

**New teammates:** follow **[docs/HOW_TO_RUN.md](docs/HOW_TO_RUN.md)**.

Secrets (WordPress application password, Google OAuth Client ID/secret, login tokens) are not in this repo. Each person stores them in a local `.mds/` folder.
