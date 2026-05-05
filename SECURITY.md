# Security Policy

## Supported Versions

Only the latest version on the `main` branch is supported for security updates.

| Version | Supported          |
| ------- | ------------------ |
| v0.2.x  | :white_check_mark: |
| < v0.2  | :x:                |

## Reporting a Vulnerability

We take the security of Parallax seriously. Since this project currently operates in **Dry-Run/Simulated** mode with no live wallet or custody handling, vulnerabilities should focus on:
- Execution bypass in simulation
- Proof manipulation
- API unauthorized access
- Data integrity in the audit trail

Please report it privately. Do **not** create a public GitHub issue.

You can contact the core maintainers at `security@parallax.io` (placeholder).

## Responsible Disclosure

We ask that you follow responsible disclosure practices:
- Give us a reasonable amount of time to fix the issue before making it public.
- Do not exploit the vulnerability beyond what is necessary for the Proof of Concept.
- Do not attempt to access other users' data.
