# Contributing to Token Cost Estimator

Thank you for your interest in contributing to **Token Cost Estimator**! This project is a production-grade FastAPI + PostgreSQL FinOps service engineered to calculate LLM token costs, enforce atomic team/application budgets, reconcile estimates with actuals, and generate anomaly alerts.

---

## 🎓 For Learners & Students

Reading and running the codebase is highly encouraged:
- The [`Learning/`](Learning/) study guide and [`docs/`](docs/) are designed to help you explore production backend patterns.
- Questions are welcome as GitHub issues (tagged `question`).
- Small, focused PRs that fix bugs, improve test coverage, or clarify documentation are warmly appreciated.

---

## 🛠️ Local Development Setup

### Prerequisites

- **Python:** 3.12 or newer
- **Package Manager:** [uv](https://docs.astral.sh/uv/) (`>= 0.4.0`)
- **Database:** PostgreSQL 14 or newer (or Docker)
- **Docker & Docker Compose** (optional for containerized setup)

### Quick Bootstrap

```bash
# 1. Install dependencies, initialize test/dev databases, run migrations, and seed pricing
make setup

# 2. Run the development server with live reload
make run

# 3. Verify the installation with the interactive portfolio demo
make demo
```

---

## 🧪 Quality Gates & Validation

Before submitting a Pull Request, ensure all quality gates pass locally. The CI workflow enforces these checks on all pull requests and pushes to `main`:

```bash
# Run Ruff linting and formatting verification
make lint

# Execute static type analysis with Mypy in strict mode
make typecheck

# Run full test suite (unit + integration + contract against real PostgreSQL)
make test

# Verify test coverage meets or exceeds the 80% gate
make coverage

# Audit dependencies and scan for accidental secrets
make security-check
```

### Git Pre-commit Hooks

To automatically run formatters, linters, and type checks before committing:

```bash
make precommit  # or: uv run pre-commit install
```

---

## 🏛️ Engineering Conventions & Architectural Rules

1. **Strict Decimal Financial Math (ADR-001):**
   - Floating-point arithmetic (`float`) is strictly prohibited in cost calculation, budget enforcement, and storage.
   - Always use `Decimal` with the precision defined in `src/app/utils/money.py`. All API money values are serialized as formatted strings.

2. **Clean Layered Architecture:**
   - **API Routes (`src/app/api/`):** Thin controllers handling HTTP contracts, input validation, and dependency injection.
   - **Services (`src/app/services/`):** Pure orchestration and business logic. Services never touch database sessions directly.
   - **Repositories (`src/app/repositories/`):** Own all SQLAlchemy 2.0 async database queries and transactional boundaries.
   - **Domain Protocols (`src/app/domain/`):** Core domain abstractions (`TokenCounter`, `PricingProvider`, `LLMProvider`) sit behind `Protocol` interfaces.

3. **Concurrency & Atomicity (ADR-003):**
   - Budget evaluation and reservations rely on PostgreSQL row locks (`SELECT ... FOR UPDATE`) within ACID transactions to eliminate race conditions without distributed lock overhead.

4. **Pricing Versioning (ADR-005):**
   - Historical usage records snapshot their `pricing_version` to guarantee immutability against future price changes.

5. **Privacy & Security (ADR-007):**
   - Prompt and completion texts are processed in memory and must **never** be logged, cached, or persisted to the database.
   - Secrets, API keys, and authorization headers are automatically redacted by structured logging processors.

---

## 🌿 Branching & Pull Request Workflow

1. Fork or branch from `main`:
   ```bash
   git checkout -b feat/your-feature-name  # or fix/your-bugfix-name
   ```
2. Keep commits atomic, well-tested, and accompanied by relevant documentation.
3. Verify all checks pass via `make test` and `make coverage`.
4. Open a Pull Request using the provided PR template, clearly describing the architectural context, rationale, and verification steps.

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the project's [MIT License](LICENSE).
