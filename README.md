# SENTINEL

SENTINEL is a transaction-integrity and anomaly-control plane designed to operate around an existing Core Banking System (CBS). The CBS remains the authoritative financial source of truth; SENTINEL does not implement a competing ledger.

## Phase 0: Foundation

The repository currently contains the Python packaging, configuration, structured logging setup, test scaffold, and CI foundation for the project. Financial transaction behavior begins in a later phase and is intentionally not included here.

## Development

Create an environment and install development dependencies:

```text
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the checks:

```text
python -m pytest
ruff check .
mypy src
```

The packaged entry point is available after installation:

```text
sentinel
```

The runtime configuration is read from environment variables. See `.env.example` for safe local defaults. Secrets and production credentials must not be committed.

Production concerns such as transaction state, durable persistence, authentication, authorization, audit, observability, deployment, and disaster recovery are intentionally deferred to the later phases in the master specification.

## Scope

The build specification in `MASTER_BUILD_PROMPT.md` is the authoritative roadmap. Each phase is implemented and validated separately, with commits and tags created only after approval of its phase gate.
