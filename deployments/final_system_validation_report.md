# Final System Validation Report

## Scope

This report documents the repository evidence for the SENTINEL v1.0.0 release and the subsequent `feature/simulation-ui` development branch. The frozen `v1.0.0` tag remains a historical release reference; additional commits on the feature branch extend the simulated development surface.

The evidence in this report is derived from the repository code and tests, not from invented deployment infrastructure. The repository is a deterministic Python package, a FastAPI contract surface, and an evidence-backed control-plane model around an authoritative CBS. It is not a production bank deployment or live-ledger integration. The current feature branch includes simulation and banking UI surfaces implemented only against synthetic adapters.

## Exact startup command

```sh
cd d:\Projects\cbs_sentinel\SENTINEL
.\.venv\Scripts\python.exe -m sentinel.main
```

This command runs the shipped Python entrypoint. It loads environment-backed settings, applies security validation, and configures logging. It does not open a UI or start an external HTTP web server.

## Environment prerequisites

The final repository configuration requires:

- Python >= 3.12
- A virtual environment containing the repository dependencies from `pyproject.toml`
- Optional environment variables for configuration:
  - `SENTINEL_ENVIRONMENT`
  - `SENTINEL_LOG_LEVEL`
  - `SENTINEL_DATABASE_URL`
  - `SENTINEL_DB_POOL_SIZE`
  - `SENTINEL_DB_MAX_OVERFLOW`
  - `SENTINEL_REDIS_URL`
  - `SENTINEL_REDIS_MAX_CONNECTIONS`
  - `SENTINEL_MTLS_REQUIRED`
  - `SENTINEL_MIN_TLS_VERSION`
  - `SENTINEL_SECRETS_BACKEND`
  - `SENTINEL_KMS_PROVIDER`
  - `SENTINEL_HSM_REQUIRED`
  - `SENTINEL_IAM_BACKEND`

The repository also expects the dependency set in `pyproject.toml` to be installed, including `fastapi`, `aiokafka`, `redis`, `SQLAlchemy[asyncio]`, and `asyncpg`.

## API endpoints

The visible FastAPI surface is derived from the actual `create_api(...)` factory in the shipped code. The route surface is:

- `GET /api/v1/health`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions/{transaction_id}/status`

The route proof command was:

```sh
cd d:\Projects\cbs_sentinel\SENTINEL
.\.venv\Scripts\python.exe -c "from sentinel.application.api import create_api; from tests.unit.test_enterprise_api import FakeOrchestrator, Auth, ApiTestClient, body; app = create_api(FakeOrchestrator(), authentication=Auth()); route = [r.path for r in app.routes if getattr(r, 'path', None) in ('/api/v1/health','/api/v1/transactions','/api/v1/transactions/{transaction_id}/status')]; print(route)"
```

Verified output:

```text
['/api/v1/health', '/api/v1/transactions', '/api/v1/transactions/{transaction_id}/status']
```

## 203-test result

Fresh full regression proof command on the `feature/simulation-ui` branch:

```powershell
cd d:\Projects\cbs_sentinel\SENTINEL
$env:SENTINEL_DATABASE_URL = "postgresql+asyncpg://sentinel_user:<password>@127.0.0.1:5432/sentinel"
.\.venv\Scripts\python.exe -m pytest -q
```

Fresh output:

```text
203 passed in 9.82s
```

## Successful transaction proof

The shipped API test pattern uses `ApiTestClient` and `create_api()` to issue a valid POST to `/api/v1/transactions` with a valid bearer token and `Idempotency-Key` header.

Fresh proof command:

```sh
cd d:\Projects\cbs_sentinel\SENTINEL
.\.venv\Scripts\python.exe -c "import asyncio, httpx; from sentinel.application.api import create_api; from sentinel.application.api.app import APIError, DefaultPrincipal; from sentinel.domain.integrity import IntegrityDecision, IntegrityDecisionCode; from sentinel.domain.protection import ProtectiveAction, ProtectiveDecision; from sentinel.domain.transactions import Transaction; from tests.unit.test_enterprise_api import FakeOrchestrator, Auth, ApiTestClient, body; client = ApiTestClient(create_api(FakeOrchestrator(), authentication=Auth())); headers={'Authorization':'Bearer valid','Idempotency-Key':'api-idem-1','X-Correlation-ID':'corr-1','X-Trace-ID':'trace-1'}; response = client.post('/api/v1/transactions', json=body(), headers=headers); print(response.status_code); print(response.json())"
```

Fresh output:

```text
200
{'transaction_id': 'api-txn-1', 'state': 'RECEIVED', 'correlation_id': 'corr-1', 'trace_id': 'trace-1', 'integrity_code': 'ALLOW', 'protective_action': 'ALLOW'}
```

This confirms that the proofed API surface can accept an authenticated transaction request and produce a structured decision response. It also proves the stored transaction response object carries the required correlation and trace headers.

## Duplicate-request proof

The repository’s `test_idempotency_key_cannot_be_reused_for_a_different_request()` scenario in [tests/unit/test_enterprise_api.py](tests/unit/test_enterprise_api.py) demonstrates the required duplicate safety proof:

- First POST succeeds.
- A second POST with the same `Idempotency-Key` and different request body returns `409` with `IDEMPOTENCY_KEY_CONFLICT`.

This is the documented repository proof that request fingerprints and idempotency keys are evaluated deterministically and that a conflicting payload cannot be accepted into the same idempotency lane.

## UNKNOWN/timeout proof

The repository exposes explicit status/timeout and unresolved-state behaviors in the API and the transaction engine:

- `GET /api/v1/transactions/{transaction_id}/status` returns `{"transaction_id": ..., "status": "UNKNOWN"}` when the endpoint is asked for an unresolved transaction ID.
- The FastAPI handler catches workflow `TimeoutError` and maps it to an `APIError` with HTTP `504` and code `CBS_TIMEOUT`.

These proofs are represented by the repository’s API test source in [tests/unit/test_enterprise_api.py](tests/unit/test_enterprise_api.py) and the timeout normalization in [src/sentinel/application/api/app.py](src/sentinel/application/api/app.py).

## Reconciliation proof

The repository’s reconciliation engine in [src/sentinel/domain/reconciliation/engine.py](src/sentinel/domain/reconciliation/engine.py) decides outcomes from authoritative `CBSAdapter` evidence only. The engine performs deterministic classification into:

- `RECONCILED_SUCCESS`
- `RECONCILED_FAILURE`
- `REVERSAL_REQUIRED`
- `COMPENSATION_REQUIRED`
- `MANUAL_REVIEW`
- `UNKNOWN_REQUIRES_INVESTIGATION`

The simulator adapter in [src/sentinel/adapters/cbs/simulator.py](src/sentinel/adapters/cbs/simulator.py) also exposes deterministic reconciliation scenarios such as `partial_failure`, `unknown`, `duplicate_posting`, `delayed_posting`, and `reconciliation`. This is the repository’s concrete evidence for reconciliation proof and investigation boundaries.

## Redis/Kafka/PostgreSQL connectivity

The repository is designed around external service contracts:

- Redis coordination is represented by [src/sentinel/infrastructure/coordination/redis.py](src/sentinel/infrastructure/coordination/redis.py), which is an advisory, non-authoritative coordination layer with fail-closed rate-limit behavior. It handles cache, lock, idempotency hint, and rate-limit checks. The rate-limit path rejects when Redis is unavailable by returning a deny decision.
- Kafka publishing is represented by [src/sentinel/infrastructure/events/producer.py](src/sentinel/infrastructure/events/producer.py); it uses `AIOKafkaProducer` and emits an `EventEnvelope` with bounded retries and `KafkaPublishError` on failure.
- PostgreSQL persistence is represented by [src/sentinel/infrastructure/persistence/database.py](src/sentinel/infrastructure/persistence/database.py) and the integration tests in [tests/integration/test_postgresql_persistence.py](tests/integration/test_postgresql_persistence.py). The repository expects a `postgresql+asyncpg://` URL and enforces an async PostgreSQL engine model.

The repository’s integration tests prove the local shapes and schemas but are not a production deployment. A running PostgreSQL database and proper environment variables are prerequisites for a full service-proof environment.

## Simulator limitations

The main simulator adapter in [src/sentinel/adapters/cbs/simulator.py](src/sentinel/adapters/cbs/simulator.py) is explicitly non-authoritative and non-ledger-producing. It deliberately remains an in-memory deterministic contract and test surface.

Its limitations are:

- It never claims authoritative ownership of balances or posted ledger effects.
- It does not implement an independent financial ledger. It only simulates adapter responses and transaction-state evidence.
- It supports scenario labels such as `timeout`, `duplicate_request`, `partial_failure`, `unknown`, `reconciliation`, and `cbs_unavailable` for deterministic contract review.
- It is not a production-grade bank integration.

## Known production-integration boundaries

The repository’s documented gate and architecture posture is explicit:

- CBS remains the authoritative bank source of truth.
- SENTINEL remains a control plane around the existing bank model.
- Redis is advisory and non-authoritative.
- PostgreSQL is the durable metadata and audit host, while the bank ledger remains authoritative.
- A production deployment requires external IAM, mTLS verification, and external secrets/KMS control.
- The API’s production environment guard requires an external IAM and mTLS verifier in [src/sentinel/application/api/app.py](src/sentinel/application/api/app.py).

Therefore, the valid production integration story for this repository is evidence-backed orchestration, not an actual bank transaction posting service.

## Release commit/tag and current branch state

The frozen production release metadata remains:

```text
Commit: 72dd7e5a0f0ae5bb26b8d93070f5d3e332bbc832
Tag:    v1.0.0
```

The subsequent development branch is currently:

```text
Branch: feature/simulation-ui
HEAD:   d23ae35d8a0c4a8a0d1941a1d589139c0002e1f6
Version description: v1.0.0-9-gd23ae35
```

The worktree is clean. The current branch contains approved simulation UI and integration-boundary development after the frozen `v1.0.0` release; this report therefore distinguishes the historical release evidence from the current feature branch evidence.
