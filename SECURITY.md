# Security Policy

## Supported Versions

We actively support and provide security fixes for the latest release:

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

---

## Reporting a Vulnerability

We take the security of Token Cost Estimator seriously. If you believe you have found a security vulnerability, please do not open a public GitHub issue.

Instead, please report security vulnerabilities responsibly via email or GitHub Private Vulnerability Reporting:

- **Security Contact:** [pranjulyabajpai@gmail.com](mailto:pranjulyabajpai@gmail.com)
- **Subject:** `[SECURITY] Token Cost Estimator Vulnerability Report`

### What to Include

Please provide:
- A description of the vulnerability and its potential impact.
- Clear steps to reproduce or a minimal proof-of-concept.
- Any affected endpoints, environment configurations, or dependencies.

We will acknowledge receipt of your report within 48 hours and work with you to coordinate a responsible disclosure timeline and patch release.

---

## Security Architecture & Design Guarantees

- **Zero Prompt Retention:** Prompt and completion texts are never written to disk, databases, or access logs.
- **Strict Decimal Precision:** Financial computations prevent floating-point exploitation or precision manipulation.
- **Log Redaction:** All structured loggers redact authorization tokens, API keys, and sensitive request payloads by default.
- **Role-Based Auth & Rate Limiting:** All `/v1/` endpoints enforce API key authentication, permission scopes (`user` vs `admin`), and per-key rate-limiting buckets.
