# DevSecOps

This page describes how security is enforced in the digital thread: the CI
workflow, the local `mbse security` gate, the policy each scanner contributes,
and the repository settings that keep `main` trustworthy.

The same set of checks runs in two places:

- `.github/workflows/security.yml` on every pull request and on pushes to
  `main` that touch `requirements/`, `models/`, `src/`, `pipeline/`, `infra/`,
  or `.github/workflows/`.
- `mbse security` locally (and in the workflow's `summary` job), which writes
  `build/reports/security.json` and `build/reports/security.sarif`.

CI additionally uploads Bandit, Semgrep, Trivy, and Checkov results to GitHub
code scanning as SARIF. The workflow runs with `contents: read` and
`security-events: write` only; it uses the default `GITHUB_TOKEN` and no other
secrets.

## Gate policy

A finding at or above the listed severity fails the gate (`gate_failed`
returns true and `mbse security` exits non-zero). Lower-severity findings are
still reported.

| Tool | Gate | Rationale |
|---|---|---|
| Gitleaks | Any finding | A committed credential is always release-blocking; rotation, not suppression, is the fix. |
| Bandit | High severity | High-confidence high-severity patterns (injection, unsafe deserialization, weak crypto) are exploitable. |
| Semgrep | High severity | The `p/python` ruleset's high-severity findings are treated the same as Bandit's. |
| pip-audit | Any known vulnerability (treated as high) | A pinned dependency with a published advisory needs an upgrade or a documented exception. |
| Trivy (filesystem) | Critical | Critical vulnerable packages, secrets, or misconfigurations fail; high findings are reported for triage. |
| Checkov (IaC) | High | Public buckets, missing encryption/versioning, and permissive policies fail. |
| Security requirements | `SEC-001` | Every approved `type: security` requirement must have at least one `@pytest.mark.req(...)` test. |
| Traceability | `TRC-006` | Same rule expressed through the traceability checker: a security requirement with no req-tagged test is an error naming the requirement. |

The tool order in the report is fixed: gitleaks, bandit, semgrep, pip-audit,
trivy, checkov. Reports are deterministic — no timestamps, sorted findings and
components — so a clean `git diff` after regeneration is meaningful.

## Local fallbacks and fail-closed behavior

Each scanner reports a status of `passed`, `failed`, `unavailable`, or `error`.

- **Gitleaks**: when the `gitleaks` binary is absent, a built-in Python scanner
  walks tracked/working files (skipping `.git`, `.venv`, `build`, `site`, and
  `node_modules`) and flags AWS access key IDs, GitHub tokens, private-key
  headers, and long `api_key`/`api_token`/`secret`/`password` literals.
  Key-like matches are `critical`; the generic assignment pattern is `high`.
- **Bandit**: runs `bandit -r src pipeline/mbse -f json -q` when installed;
  otherwise reports `unavailable` with a note.
- **Semgrep, pip-audit, Trivy, Checkov**: run only when the executable is
  present; otherwise they report `unavailable` with an explanatory note.

Unavailable tools are visible in `security.json`, but they do **not** silently
pass policy: CI installs and runs every scanner in dedicated jobs, so a tool
that is missing locally is still enforced before merge. Treat an `unavailable`
result locally as "not verified here", not as a pass, and run the tool (or rely
on CI) before declaring the change secure. The requirement checks
(`SEC-001`, `TRC-006`) are pure Python and never depend on an external binary.

## Branch protection

Configure `main` with:

- **Required status checks**: `Secret scanning (gitleaks)`,
  `Static analysis (bandit, semgrep)`, `Dependency audit (pip-audit, SBOM)`,
  `Filesystem scan (trivy)`, `Infrastructure as code (checkov)`, and
  `Security gate (mbse security)`. Also require the test and documentation
  jobs once they exist.
- **Require a pull request before merging** with at least one approving review
  from a code owner; dismiss stale approvals when new commits are pushed.
- **Require signed commits** on `main` (or organization-wide commit signing),
  so every change carries a verifiable author identity.
- **Require conversation resolution**, **require linear history**, and block
  force pushes and deletions.
- **Do not allow bypass** for administrators, so the gate cannot be skipped
  during an incident review.

## Optional: keyless image signing with Cosign

Container images published from this repository can be signed without
long-lived keys using Sigstore's OIDC flow:

```bash
# After `docker build -t ghcr.io/<owner>/thermostat:<sha> .`
COSIGN_EXPERIMENTAL=1 cosign sign ghcr.io/<owner>/thermostat:<sha>
# Verify against the workflow identity that produced the image
cosign verify ghcr.io/<owner>/thermostat:<sha> \
  --certificate-identity-regexp '^https://github.com/<owner>/<repo>/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The signature is recorded in the transparency log, and verification binds the
image to the GitHub Actions workflow identity rather than to a stored private
key. Signing is optional for this project; when enabled, add `id-token: write`
to the publishing job only.

## Reproducing a seeded secret failure locally

The fallback scanner makes it possible to prove the gate works without
installing Gitleaks:

1. Create a throwaway file containing a fake credential, for example:

   ```bash
   printf 'aws_access_key_id = "AKIA_EXAMPLE"\n' > leaked.tmp
   ```

2. Run the gate:

   ```bash
   mbse security
   ```

   The output lists the gitleaks result, the finding points at `leaked.tmp`,
   and the command exits with status 1 because Gitleaks fails on any finding.

3. Inspect `build/reports/security.json` (per-tool status and severity counts)
   and `build/reports/security.sarif` (code-scanning compatible).

4. Delete the file and re-run:

   ```bash
   rm leaked.tmp
   mbse security
   ```

   The gate passes again. The allowlist in `.gitleaks.toml` intentionally
   covers only dependency and generated paths (`.venv/`, `build/`, `site/`,
   SBOM/SARIF outputs), so a real secret in source can never hide behind it.

If the file was committed, rotate the credential first; adding a suppression
or allowlist entry is not an acceptable fix.
