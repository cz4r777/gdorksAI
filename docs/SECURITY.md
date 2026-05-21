# gdorksAI — Security & Responsible Use

## Authorized use only

gdorksAI is built for **authorized penetration testing, bug-bounty work, defensive research, and education**.

Using this tool to enumerate targets you are not authorized to test is:
- a violation of the Computer Fraud and Abuse Act (US) and equivalent statutes elsewhere,
- a violation of Google's Terms of Service,
- a violation of this project's license and code of conduct.

**You are responsible for confirming you have authorization before each engagement.**

## Built-in guardrails

The tool ships with the following ethics rails. Do not disable them in contributed PRs.

1. **Scope guard (`app/core/scope.py`)** — every render/query/triage/pivot/report call validates the target domain against `runtime/scope.json`. Out-of-scope targets are refused and logged.
2. **No automatic execution** — the tool never sends traffic to Google or the target. The operator clicks URLs manually in their own browser.
3. **Local-first AI** — Ollama is the default backend. No outbound calls until the operator explicitly sets `GROQ_API_KEY`.
4. **Session data is local** — `runtime/sessions/` stays on disk. Reports are saved locally; the operator decides whether to share them.
5. **No credential storage** — the tool does not store target credentials, cookies, or session tokens.

## Threat model (v0.1)

Assets:
- Operator's engagement scope (sensitive: identifies real targets under contract).
- Operator's findings (sensitive: pre-disclosure vulnerabilities).
- Operator's AI prompts/responses (semi-sensitive: may include target context).

Adversaries we defend against:
- **Operator misuse (accidental)** — operator types the wrong domain. Scope guard catches this.
- **Operator misuse (intentional)** — out of scope; the tool is not a containment system for hostile operators.
- **Local malware** — out of scope; assume operator workstation is trusted.

Adversaries we do **not** defend against:
- Targeted compromise of the operator's machine.
- Side-channel inference of scope from network metadata if Groq fallback is enabled.

## Reporting a security issue

Do **not** file a public issue. Open a private security advisory on the GitHub repo, or email the maintainer.

Critical issues (auth bypass, scope-guard bypass, secret exfiltration, AI prompt injection that bypasses scope) get a hot-fix per [PIPELINE.md](PIPELINE.md#hot-fix-path).

## Disclosure policy

If you find a security vulnerability **on a target while using this tool**, follow responsible disclosure to the affected vendor. Do not publish, exploit, or sell the finding.
