# SENTINEL Simulation Console

The simulation console is a browser-based test surface for the deterministic CBS adapter. It exercises the same orchestration boundary used by the API while keeping the simulator explicitly non-authoritative.

## Start the console

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn sentinel.application.simulation_server:app --app-dir src --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/simulation-ui>.

The page is available only as a local simulation tool. It does not post to a bank ledger or create authoritative balances.

## API surface

- `GET /api/v1/simulator/health` reports simulation mode and the authority boundary.
- `GET /api/v1/simulator/scenarios` lists the deterministic scenario catalog.
- `POST /api/v1/simulator/transactions` submits a scenario-driven transaction.
- `POST /api/v1/simulator/scenarios/{scenario}/execute` selects the scenario in the URL.
- `GET /api/v1/simulator/transactions/{transaction_id}` returns the stored simulation result.
- `GET /api/v1/simulator/transactions/{transaction_id}/events` returns lifecycle history.

Simulation writes require a bearer token and an `Idempotency-Key`, matching the API contract. The bundled console uses a local test token for development only.

## Scenario interpretation

- `normal_transaction` exercises the normal acceptance path.
- `timeout`, `cbs_unavailable`, and `lost_response` resolve to an unresolved outcome; they must not be presented as financial success.
- `unknown`, `partial_failure`, `duplicate_posting`, `delayed_posting`, and `reconciliation` produce reconciliation evidence or pending review states.
- `duplicate_request` exercises idempotent request handling.
- `reversal` exercises reversal capability metadata.

A CBS timeout caught inside orchestration becomes `UNKNOWN` and requests reconciliation. An outer API request deadline may instead return HTTP `504`; these are deliberately different outcomes.

## Boundary

The simulator is deterministic and in-memory. It does not implement a competing ledger, authoritative account balances, production IAM, mTLS, Kafka delivery, Redis durability, or a real CBS integration. Production adapters must implement the same CBS port and remain the source of authoritative posting evidence.
