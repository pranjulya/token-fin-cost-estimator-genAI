## Description

<!-- Provide a concise summary of the changes and the rationale behind them. -->

## Type of Change

- [ ] 🐛 Bug fix (non-breaking change fixing an issue)
- [ ] ✨ New feature (non-breaking change adding functionality)
- [ ] ⚡ Performance improvement
- [ ] 🔒 Security hardening
- [ ] 📚 Documentation update
- [ ] 🧪 Test suite enhancement
- [ ] 🏗️ Architecture / Refactoring

## Architectural & FinOps Impact

- [ ] Modifies pricing calculation, token counting, or currency representation (`Decimal`)
- [ ] Changes budget reservation, locking (`SELECT ... FOR UPDATE`), or settlement logic
- [ ] Introduces database schema changes (includes Alembic migration)
- [ ] Affects security, auth scopes (`user` vs `admin`), or rate limiting

## Verification & Testing

<!-- List the steps and commands executed to verify changes. -->

- [ ] `make lint` passed (`ruff check` & `ruff format`)
- [ ] `make typecheck` passed (`mypy src --strict`)
- [ ] `make test` passed (unit + integration + contract tests against Postgres)
- [ ] `make coverage` met coverage gate (>= 80%)
- [ ] `make security-check` passed (dependency audit & secret scan)

## Checklist

- [ ] My code follows the project's architectural guidelines and style standards.
- [ ] I have updated relevant documentation in `/docs` (or ADRs if architectural change).
- [ ] No secrets, prompts, or personally identifiable information are logged or committed.
