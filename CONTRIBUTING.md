# Contributing to Parallax

Thank you for your interest in contributing to Parallax, the Hybrid HFT Arbitrage Engine for Prediction Markets.

## Development Stack

- **Backend**: Python 3.12+ (managed via `uv`)
- **Core Engine**: Rust (compiled via `maturin`)
- **Database**: PostgreSQL (SQLAlchemy 2.0) + Neo4j (Graph)
- **Frontend**: React + TypeScript + Vite

## Getting Started

1.  **Clone the repository**.
2.  **Install dependencies**:
    ```bash
    make install
    ```
3.  **Setup local environment**:
    ```bash
    cp .env.example .env
    # Add your ANTHROPIC_API_KEY
    ```
4.  **Launch Infrastructure**:
    ```bash
    make up
    make migrate
    ```

## Coding Standards

- We use **Black** for formatting and **Ruff** for linting.
- Every new feature must include unit or integration tests in the `tests/` directory.
- For Rust changes, ensure `cargo test` passes before running `maturin develop`.

## Architecture Principles

- **The Hot Path (Rust)**: Must remain deterministic and zero-allocation where possible. No I/O in the core solver.
- **The Cold Path (Python/LLM)**: Handles high-level semantic reasoning and graph discovery.
- **No Proof, No Bet**: Every trade must be backed by a `TradeProofCertificate`.

## Pull Request Process

1.  Create a feature branch from `main`.
2.  Ensure the full test suite passes: `make test`.
3.  Open a PR with a clear description of the change and its impact on latency/risk.

## Security

Please do not report security vulnerabilities through public GitHub issues. Use the contact information in `SECURITY.md`.
