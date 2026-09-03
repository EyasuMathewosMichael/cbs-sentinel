# SENTINEL — MASTER BUILD PROMPT

## Core Banking Transaction Integrity & Anomaly Sentinel

**Document Type:** Master AI Build Specification  
**Project:** SENTINEL  
**System:** Core Banking Transaction Integrity & Anomaly Sentinel  
**Target:** Production-grade enterprise banking infrastructure  
**Primary Development Environment:** VS Code  
**Recommended Agent Mode:** Autonomous coding/agent mode with terminal, filesystem, and test execution access

---

# 0. MASTER INSTRUCTION

You are the **Principal Software Architect, Senior Distributed-Systems Engineer, Banking Infrastructure Engineer, Security Engineer, DevSecOps Engineer, Reliability Engineer, and QA Lead** responsible for building the SENTINEL platform.

You are not building a university demonstration, toy project, prototype-only application, or startup MVP.

You are building a **production-oriented enterprise transaction-integrity control plane** designed to operate around existing Core Banking Systems (CBS), payment switches, banking channels, and related financial infrastructure.

Your job is to progressively implement SENTINEL in the repository, validate every phase, detect architectural or implementation problems, fix them, and only then proceed.

You must prioritize:

1. Financial transaction integrity
2. Correctness
3. Safety
4. Deterministic behavior
5. Idempotency
6. Reconciliation
7. Security
8. Reliability
9. Observability
10. Performance
11. Maintainability
12. Testability
13. Operational readiness

Do not sacrifice financial correctness for performance.

Do not sacrifice safety for convenience.

Do not silently invent financial behavior.

When requirements are ambiguous, choose the safest architecture and document the assumption.

---

# 1. SYSTEM DEFINITION

SENTINEL is an independent:

> **Core Banking Transaction Integrity & Anomaly Sentinel**

It operates as a control plane around existing banking infrastructure.

Its responsibilities include:

- Transaction integrity validation
- Balance integrity validation
- Idempotency
- Transaction lifecycle/state management
- Transaction journal
- Risk evaluation
- Rule-based anomaly detection
- Statistical anomaly detection
- Behavioral anomaly detection
- System-wide anomaly detection
- ML-assisted anomaly detection
- Reconciliation
- Protective response
- Failure containment
- Recovery coordination
- Audit
- Observability
- Operational resilience

SENTINEL must NOT become the authoritative financial ledger.

---

# 2. NON-NEGOTIABLE ARCHITECTURAL PRINCIPLE

## CBS remains authoritative.

The fundamental rule of the entire project is:

> **The Core Banking System remains the authoritative financial source of truth. SENTINEL is an independent control plane for transaction integrity, anomaly detection, reconciliation, risk, and protective response.**

Never violate this rule.

SENTINEL must not create an independent competing financial ledger.

SENTINEL may maintain:

- Transaction metadata
- Expected state
- Transaction journal
- Decision records
- Observations
- Risk assessments
- Reconciliation cases
- Audit records
- Operational state

But SENTINEL must not claim authoritative ownership of the bank's financial ledger.

---

# 3. PRIMARY PROBLEM TO SOLVE

One of the critical banking failure scenarios SENTINEL must handle is:

```text
Customer A
   │
   │ Transfer 1,000 ETB
   ▼
SENTINEL
   │
   ▼
CBS
   │
   ├── Source account debited
   │
   ├── Network/service failure
   │
   └── Destination account NOT credited
```

The system must NOT blindly retry the transaction.

Instead:

```text
Request
   ↓
Idempotency validation
   ↓
Transaction submitted
   ↓
Timeout / uncertain response
   ↓
UNKNOWN state
   ↓
Query authoritative CBS state
   ↓
Check posting state
   ↓
Check destination state
   ↓
Reconcile
   ↓
Determine final outcome
   ↓
Reverse / compensate / complete / manual review
```

This behavior is a core requirement.

---

# 4. FINANCIAL SAFETY RULES

Implement these rules throughout the system.

## Rule 1 — Never blindly retry an uncertain financial transaction

A timeout does NOT mean failure.

A timeout means:

```text
UNKNOWN
```

until the authoritative state is determined.

---

## Rule 2 — Duplicate delivery must not create duplicate financial effects

The system must support idempotency.

Target:

> Exactly-once financial effect.

Network and event delivery may be at-least-once.

Financial effect must remain exactly-once.

---

## Rule 3 — Redis is not financial truth

Redis may be used for:

- Coordination
- Cache
- Rate limiting
- Ephemeral state
- Fast idempotency lookup
- Distributed coordination

Redis must never become the authoritative balance or ledger.

---

## Rule 4 — Cache must never override CBS

If cached information conflicts with CBS:

```text
CBS wins.
```

---

## Rule 5 — ML must not override deterministic integrity controls

For example:

```text
Debit without destination credit
```

is a deterministic integrity failure.

An ML model must not override that decision.

---

# 5. AUTHORITATIVE DATA HIERARCHY

Implement the following conceptual hierarchy:

```text
1. CBS authoritative ledger/posting
2. CBS transaction status / balance APIs
3. Approved reconciliation source
4. SENTINEL expected state
5. Cache / telemetry
```

Lower-level information must never override higher-level authoritative information.

---

# 6. TRANSACTION STATES

Implement an explicit transaction state machine.

At minimum support:

```text
RECEIVED
VALIDATING
ACCEPTED
REJECTED
SUBMITTED_TO_CBS
CBS_PROCESSING
POSTED
DESTINATION_CREDITED
SETTLED
RECONCILED
FAILED
TIMEOUT
UNKNOWN
PARTIAL_FAILURE
RETRY_PENDING
RECONCILIATION_PENDING
REVERSAL_PENDING
REVERSAL_COMPLETED
COMPENSATION_PENDING
COMPENSATION_COMPLETED
MANUAL_REVIEW
```

Do not allow arbitrary state transitions.

Every state transition must be validated.

Every important state transition must be auditable.

---

# 7. TRANSACTION LIFECYCLE

The normal lifecycle should conceptually follow:

```text
RECEIVED
   ↓
VALIDATING
   ↓
IDEMPOTENCY_CHECK
   ↓
INTEGRITY_CHECK
   ↓
RISK_EVALUATION
   ↓
POLICY_DECISION
   ↓
ACCEPTED
   ↓
SUBMITTED_TO_CBS
   ↓
CBS_PROCESSING
   ↓
POSTED
   ↓
DESTINATION_CREDITED
   ↓
SETTLED
   ↓
RECONCILED
```

Failure paths must be explicitly modeled.

---

# 8. UNKNOWN TRANSACTIONS

UNKNOWN is a first-class state.

Examples:

```text
CBS timeout
Network timeout
Service crash after submission
Connection lost after request
Partial downstream response
Unknown payment-switch result
```

When UNKNOWN occurs:

1. Do not blindly retry.
2. Persist the uncertainty.
3. Query authoritative transaction status.
4. Check source account state.
5. Check destination state where available.
6. Check posting state.
7. Attempt reconciliation.
8. Determine final outcome.
9. Initiate approved reversal/compensation if necessary.
10. Escalate to manual review when automated resolution is unsafe.

Monitor:

```text
unknown_transaction_count
unknown_transaction_age
unknown_transaction_backlog
```

These are critical operational metrics.

---

# 9. IDEMPOTENCY

Implement durable idempotency.

Each financial request should have a unique idempotency identity.

Possible identifiers:

```text
transaction_id
request_id
idempotency_key
channel_id
```

The system must handle:

- Duplicate requests
- Request replay
- Network retry
- Service restart
- Consumer retry
- Kafka duplicate delivery
- Client retry
- Concurrent duplicate requests

Idempotency records must survive process restarts.

Do not rely solely on in-memory dictionaries.

---

# 10. MULTI-ACCOUNT TRANSACTION CONSISTENCY

Transfers often involve multiple financial effects.

For example:

```text
Source Account
      ↓
     DEBIT
      ↓
Destination Account
      ↓
    CREDIT
```

The system must recognize that:

```text
DEBIT SUCCESS + CREDIT FAILURE
```

is not equivalent to:

```text
TRANSACTION FAILED
```

It is:

```text
PARTIAL_FAILURE
```

This must trigger reconciliation/recovery logic.

---

# 11. REVERSAL AND COMPENSATION

Implement controlled recovery states.

Do not assume reversal is always available.

Support adapter capabilities such as:

```text
supports_reversal()
supports_compensation()
supports_status_query()
supports_balance_query()
```

A reversal must have its own:

- Transaction identity
- Idempotency identity
- State
- Audit trail
- Result
- Retry policy

Never create an uncontrolled reversal loop.

---

# 12. RISK ENGINE

Implement a risk engine separate from deterministic integrity validation.

Risk inputs may include:

- Amount
- Velocity
- Transaction frequency
- Account history
- Channel
- Device context
- Timing
- Transaction type
- Previous failures
- Retry frequency
- System anomaly context

Risk decisions must be explainable and traceable.

Store:

```text
decision_id
policy_version
rule_version
model_version
configuration_version
risk_score
decision
timestamp
```

---

# 13. POLICY ENGINE

Implement a configurable policy engine.

Possible decisions:

```text
ALLOW
REJECT
HOLD
REQUIRE_REVIEW
RECONCILE
BLOCK_RETRY
TRIGGER_REVERSAL
TRIGGER_COMPENSATION
TRIP_CIRCUIT_BREAKER
```

Policies must be versioned.

A transaction decision must always be traceable to the policy/configuration that produced it.

---

# 14. ANOMALY DETECTION

Implement multiple layers.

## Deterministic anomaly detection

Examples:

```text
Duplicate transaction
Debit without credit
Balance mismatch
Invalid state transition
Unexpected transaction amount
Invalid account state
Impossible transaction sequence
```

## Statistical anomaly detection

Examples:

```text
Transaction volume spike
Latency spike
Error-rate spike
Timeout spike
Unusual amount distribution
```

## Behavioral anomaly detection

Examples:

```text
Unusual customer behavior
Unusual account behavior
Unusual channel behavior
```

## System-wide anomaly detection

Examples:

```text
CBS degradation
Payment switch degradation
Kafka lag
Database latency
Redis failures
Network failures
Transaction timeout surge
```

## ML anomaly detection

ML may provide supplementary signals.

Never allow ML to override deterministic financial integrity controls.

---

# 15. RECONCILIATION ENGINE

Build reconciliation as a first-class subsystem.

It must compare:

```text
Expected transaction state
        VS
Observed CBS state
        VS
Payment/settlement state
```

Possible results:

```text
RECONCILED_SUCCESS
RECONCILED_FAILURE
REVERSAL_REQUIRED
COMPENSATION_REQUIRED
MANUAL_REVIEW
UNKNOWN_REQUIRES_INVESTIGATION
```

Reconciliation must be repeatable and idempotent.

---

# 16. TRANSACTION JOURNAL

Maintain a durable transaction journal.

Record:

```text
transaction_id
request_id
idempotency_key
source_account
destination_account
amount
currency
transaction_type
state
previous_state
new_state
timestamp
actor
decision
CBS_reference
error_code
metadata
```

Do not store sensitive information unnecessarily.

---

# 17. CBS ADAPTER ARCHITECTURE

Create an abstract CBS adapter interface.

Example:

```python
class CBSAdapter(Protocol):
    async def submit_transaction(...):
        ...

    async def get_transaction_status(...):
        ...

    async def get_account_balance(...):
        ...

    async def get_account_status(...):
        ...

    async def request_reversal(...):
        ...
```

Do not hard-code one bank's implementation into the domain layer.

Create:

```text
CBS Interface
   │
   ├── Simulator Adapter
   ├── Bank Adapter A
   ├── Bank Adapter B
   └── Future Bank Adapters
```

---

# 18. PAYMENT SWITCH ADAPTER

Use a similar adapter abstraction for payment switches.

Do not tightly couple SENTINEL to one switch vendor.

Support:

- Request submission
- Status lookup
- Settlement lookup
- Timeout handling
- Idempotency
- Reconciliation

---

# 19. APPLICATION ARCHITECTURE

Use a clean layered architecture.

```text
API
 │
 ▼
Application Layer
 │
 ▼
Domain Layer
 │
 ▼
Ports / Interfaces
 │
 ▼
Adapters / Infrastructure
```

Business logic must not be tightly coupled to:

- FastAPI
- PostgreSQL
- Redis
- Kafka
- Kubernetes
- Specific CBS vendor

---

# 20. RECOMMENDED DOMAIN STRUCTURE

```text
src/sentinel/domain/

accounts/
transactions/
balances/
integrity/
risk/
anomaly/
reconciliation/
protection/
audit/
```

Domain objects should contain financial and transaction invariants.

---

# 21. TECHNOLOGY BASELINE

Use the following baseline unless benchmarking or architectural evidence justifies a change.

### Backend

Python

### API

FastAPI

### Database

PostgreSQL

### Cache / Coordination

Redis

### Event Streaming

Apache Kafka

### Containers

Docker

### Orchestration

Kubernetes

### Metrics

Prometheus

### Dashboards

Grafana

### Distributed Tracing

OpenTelemetry

### Testing

pytest

### Dependency Management

Use modern Python packaging and dependency management.

Prefer:

```text
pyproject.toml
```

and a reproducible lock file.

---

# 22. PERFORMANCE PRINCIPLE

The system must be designed for:

- High throughput
- Low latency
- Horizontal scalability
- Predictable behavior under load

Do not prematurely claim specific TPS or latency numbers.

Benchmark first.

Performance targets must be based on measured results.

If Python/FastAPI becomes a bottleneck after realistic benchmarking, document the bottleneck and evaluate alternatives such as:

- Go
- Java
- Rust

Do not rewrite the architecture merely because another language is theoretically faster.

---

# 23. POSTGRESQL

PostgreSQL is the durable SENTINEL state store.

Use it for:

- Transactions
- Transaction attempts
- Idempotency
- Reconciliation
- Risk decisions
- Audit metadata
- Policies
- Configuration versions
- Durable operational state

Implement:

- Migrations
- Constraints
- Indexes
- Foreign keys where appropriate
- Transactions
- Connection pooling
- Backup strategy
- Health checks

---

# 24. REDIS

Use Redis for:

- Fast lookup
- Rate limiting
- Short-lived coordination
- Distributed coordination
- Cache
- Ephemeral state

Do not make Redis a source of financial truth.

The system must remain financially safe if Redis fails.

---

# 25. KAFKA

Use Kafka for asynchronous event architecture.

Potential topics:

```text
transaction.received
transaction.accepted
transaction.submitted
transaction.posted
transaction.failed
transaction.timeout
transaction.unknown
transaction.anomaly
transaction.risk
transaction.reconciled
transaction.reversed
transaction.protective_action
transaction.audit
```

Events must include:

```text
event_id
event_type
transaction_id
timestamp
producer
schema_version
correlation_id
trace_id
payload
```

Consumers must be idempotent.

Implement dead-letter handling.

---

# 26. EVENT DELIVERY SEMANTICS

Do not incorrectly promise exactly-once delivery everywhere.

Use:

```text
At-least-once delivery
+
Idempotent processing
+
Exactly-once financial effect
```

This is the preferred financial safety model.

---

# 27. API DESIGN

Implement versioned APIs.

Example:

```text
/api/v1/transactions
/api/v1/transactions/{transaction_id}
/api/v1/transactions/{transaction_id}/status
/api/v1/reconciliation/{case_id}
/api/v1/health
/api/v1/ready
```

Use:

- Request validation
- Response schemas
- Error taxonomy
- Correlation IDs
- Trace IDs
- Authentication
- Authorization
- Rate limiting
- Idempotency

---

# 28. ERROR TAXONOMY

Define structured error codes.

Examples:

```text
INVALID_REQUEST
INVALID_ACCOUNT
INVALID_AMOUNT
DUPLICATE_TRANSACTION
TRANSACTION_REJECTED
CBS_TIMEOUT
CBS_UNAVAILABLE
TRANSACTION_UNKNOWN
PARTIAL_FAILURE
BALANCE_MISMATCH
RECONCILIATION_REQUIRED
REVERSAL_REQUIRED
POLICY_REJECTED
RISK_REJECTED
INTERNAL_ERROR
```

Do not expose internal stack traces to external clients.

---

# 29. SECURITY ARCHITECTURE

Implement:

```text
mTLS
IAM
RBAC
Secrets Management
Certificate Management
Encryption in Transit
Encryption at Rest
Key Rotation
Audit Logging
Network Segmentation
Secure Configuration
Dependency Security
Container Security
```

Never commit:

```text
passwords
private keys
API secrets
production certificates
tokens
database credentials
```

Use environment variables or proper secret-management integration.

---

# 30. KEY MANAGEMENT

Production cryptographic keys must be managed securely.

Architecture should support integration with:

- Enterprise secret managers
- KMS
- HSM

Do not hard-code encryption keys.

Define:

```text
key ownership
key rotation
key versioning
key access
key revocation
key recovery
```

---

# 31. IAM AND RBAC

Implement roles appropriate to the system.

Example:

```text
SYSTEM_ADMIN
SECURITY_ADMIN
OPERATIONS_ADMIN
RECONCILIATION_OPERATOR
AUDITOR
ANALYST
SERVICE_ACCOUNT
READ_ONLY
```

Use least privilege.

Privileged operations must be auditable.

---

# 32. ADMINISTRATIVE CONTROL PLANE

High-risk administrative operations require additional controls.

Examples:

- Policy change
- Rule change
- Model activation
- Circuit breaker control
- Manual reversal
- Reconciliation override
- Production configuration change

Support:

```text
Dual control
Approval
Privileged access
Break-glass
Audit
```

---

# 33. AUDIT

Every critical decision must be auditable.

Audit record should answer:

```text
WHO?
WHAT?
WHEN?
WHERE?
WHY?
```

Capture:

```text
actor
action
transaction_id
decision_id
previous_state
new_state
policy_version
rule_version
model_version
configuration_version
timestamp
result
```

Audit records must be tamper-evident.

---

# 34. OBSERVABILITY

Implement:

```text
Metrics
Logs
Traces
Dashboards
Alerts
```

Use:

```text
Prometheus
Grafana
OpenTelemetry
Centralized Logging
```

Important metrics:

```text
transaction_total
transaction_success_total
transaction_failure_total
transaction_timeout_total
transaction_unknown_total
transaction_unknown_age
reconciliation_backlog
reconciliation_age
transaction_latency
CBS_latency
Kafka_lag
database_latency
redis_errors
circuit_breaker_state
anomaly_count
risk_decision_count
```

---

# 35. SLO / SLI

Define measurable SLOs and SLIs.

Examples:

```text
API availability
Transaction processing latency
CBS adapter latency
UNKNOWN transaction backlog
Reconciliation completion time
Event processing lag
Error rate
```

UNKNOWN transactions are particularly important.

Monitor:

```text
Number of UNKNOWN transactions
Oldest UNKNOWN transaction
UNKNOWN backlog growth
UNKNOWN resolution rate
```

---

# 36. FAILURE MODE ENGINEERING

Every dependency must have a defined failure behavior.

At minimum test:

```text
CBS unavailable
CBS timeout
CBS slow
Redis unavailable
Kafka unavailable
PostgreSQL unavailable
Policy service unavailable
Network partition
Service crash
Container restart
Message duplication
Out-of-order events
```

Never allow undefined failure behavior in financial transaction paths.

---

# 37. CIRCUIT BREAKER

Implement circuit breakers around external dependencies where appropriate.

States:

```text
CLOSED
OPEN
HALF_OPEN
```

Circuit breaker events must be audited.

Opening a circuit must not silently cause financial corruption.

---

# 38. RETRY POLICY

Retries must be classified.

Safe retries:

```text
Read-only status query
Balance query
Non-financial metadata query
Idempotent operations
```

Potentially unsafe retries:

```text
Financial posting
Debit
Credit
Transfer
Reversal
Compensation
```

Unsafe operations require idempotency and authoritative-state verification.

---

# 39. DATA PRIVACY

Apply data minimization.

Do not store unnecessary:

- PII
- credentials
- authentication secrets
- sensitive financial data

Encrypt sensitive data appropriately.

Define retention policies.

---

# 40. THREAT MODEL

Create and maintain a formal threat model.

Cover:

### External

- API abuse
- Replay
- Credential theft
- Injection
- Network attacks

### Internal

- Insider abuse
- Privilege escalation
- Unauthorized policy changes
- Fraudulent administrative actions

### Supply chain

- Vulnerable dependency
- Malicious package
- Container compromise
- CI/CD compromise

### Financial

- Duplicate debit
- Missing credit
- Balance corruption
- Incorrect reversal
- Transaction manipulation

---

# 41. TESTING ARCHITECTURE

Tests must mirror system risk.

Create:

```text
tests/
├── unit/
├── integration/
├── contract/
├── e2e/
├── performance/
├── concurrency/
├── fault_injection/
├── security/
└── fixtures/
```

---

# 42. UNIT TESTING

Test:

- State transitions
- Idempotency
- Integrity rules
- Balance rules
- Risk rules
- Policy decisions
- Reconciliation logic
- Protective responses

Financial invariants must have extensive unit coverage.

---

# 43. INTEGRATION TESTING

Test:

```text
SENTINEL ↔ PostgreSQL
SENTINEL ↔ Redis
SENTINEL ↔ Kafka
SENTINEL ↔ CBS Simulator
```

---

# 44. CONTRACT TESTING

All adapters must have contract tests.

Test:

```text
Request format
Response format
Error behavior
Timeout behavior
Authentication
Version compatibility
State semantics
```

---

# 45. END-TO-END TESTING

At minimum test:

### Successful transfer

```text
Debit
+
Credit
=
Success
```

### Debit without credit

```text
Debit
+
No credit
=
PARTIAL_FAILURE
```

### Timeout

```text
Request
+
Timeout
=
UNKNOWN
```

### Duplicate request

```text
Same idempotency key
=
No duplicate financial effect
```

### Reversal

```text
Partial failure
→
Reversal
→
Reconciled
```

---

# 46. FAULT INJECTION

Build a fault-injection framework.

Scenarios:

```text
CBS_TIMEOUT
CBS_UNAVAILABLE
CBS_SLOW
DEBIT_WITHOUT_CREDIT
DUPLICATE_REQUEST
KAFKA_FAILURE
POSTGRES_FAILURE
REDIS_FAILURE
NETWORK_DELAY
NETWORK_PARTITION
SERVICE_CRASH
MESSAGE_DUPLICATION
OUT_OF_ORDER_EVENT
```

---

# 47. CBS SIMULATOR

Build a realistic CBS simulator.

It must support:

```text
Accounts
Balances
Transactions
Transaction states
Debit
Credit
Transfers
Timeouts
Failures
Partial failures
Reversals
Status queries
Balance queries
```

The simulator is essential for development and integration testing.

---

# 48. FRAUD / ANOMALY SIMULATOR

Create test scenario generators.

Examples:

```text
Normal traffic
High-value transaction
Transaction burst
Repeated retries
Duplicate transaction
Unusual velocity
Balance mismatch
CBS outage
Payment-switch outage
Mass timeout event
```

---

# 49. PERFORMANCE TESTING

Build benchmark tooling.

Measure:

```text
TPS
Requests/sec
p50 latency
p95 latency
p99 latency
error rate
CPU
memory
database load
Kafka throughput
Redis load
```

Do not fabricate performance results.

All performance claims must come from measurements.

---

# 50. CAPACITY PLANNING

Document:

```text
Expected traffic
Peak traffic
Burst traffic
Growth assumptions
Database capacity
Kafka partition capacity
Consumer capacity
Redis capacity
CPU capacity
Memory capacity
Failover headroom
```

---

# 51. KUBERNETES

Support Kubernetes.

Structure:

```text
deployments/kubernetes/
├── base/
└── overlays/
    ├── dev/
    ├── staging/
    └── production/
```

Production deployment must include:

- Multiple replicas
- Health probes
- Resource limits
- Resource requests
- Horizontal scaling
- Pod disruption controls
- Network policies
- Secrets
- Rolling updates
- Rollback

---

# 52. ENVIRONMENT SEPARATION

Maintain:

```text
development
staging
production
```

Never use production credentials locally.

Never hard-code environment-specific secrets.

---

# 53. DISASTER RECOVERY

Define:

```text
RPO
RTO
Backup
Restore
Replication
Failover
Failback
Data consistency
Recovery procedures
```

DR must be tested.

---

# 54. REPOSITORY STRUCTURE

Implement this repository structure:

```text
sentinel/
├── README.md
├── LICENSE
├── SECURITY.md
├── CONTRIBUTING.md
├── CODEOWNERS
├── CHANGELOG.md
├── Makefile
├── pyproject.toml
├── uv.lock
├── .gitignore
├── .editorconfig
├── .pre-commit-config.yaml
├── .env.example
│
├── docs/
│   ├── architecture/
│   │   ├── context.md
│   │   ├── container.md
│   │   ├── component.md
│   │   ├── transaction-lifecycle.md
│   │   ├── state-machine.md
│   │   ├── failure-modes.md
│   │   ├── reconciliation.md
│   │   └── integration-contracts.md
│   │
│   ├── security/
│   │   ├── threat-model.md
│   │   ├── security-architecture.md
│   │   ├── key-management.md
│   │   └── incident-response.md
│   │
│   ├── operations/
│   │   ├── runbooks/
│   │   ├── slo-sli.md
│   │   ├── disaster-recovery.md
│   │   └── capacity-planning.md
│   │
│   └── adr/
│       ├── ADR-001-cbs-authority.md
│       ├── ADR-002-idempotency-semantics.md
│       └── ADR-003-event-delivery-semantics.md
│
├── src/
│   └── sentinel/
│       ├── api/
│       │
│       ├── application/
│       │   ├── commands/
│       │   ├── queries/
│       │   └── orchestration/
│       │
│       ├── domain/
│       │   ├── accounts/
│       │   ├── transactions/
│       │   ├── balances/
│       │   ├── integrity/
│       │   ├── risk/
│       │   ├── anomaly/
│       │   ├── reconciliation/
│       │   ├── protection/
│       │   └── audit/
│       │
│       ├── adapters/
│       │   ├── cbs/
│       │   ├── payment_switch/
│       │   ├── kafka/
│       │   ├── postgres/
│       │   └── redis/
│       │
│       ├── infrastructure/
│       │   ├── config/
│       │   ├── security/
│       │   ├── observability/
│       │   ├── persistence/
│       │   └── messaging/
│       │
│       └── main.py
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── e2e/
│   ├── performance/
│   ├── concurrency/
│   ├── fault_injection/
│   ├── security/
│   └── fixtures/
│
├── simulator/
│   ├── cbs/
│   ├── accounts/
│   ├── transactions/
│   ├── fault_injection/
│   ├── fraud_generator/
│   └── scenarios/
│
├── deployments/
│   ├── docker/
│   ├── compose/
│   ├── kubernetes/
│   │   ├── base/
│   │   └── overlays/
│   │       ├── dev/
│   │       ├── staging/
│   │       └── production/
│   └── helm/
│
├── infra/
│   ├── terraform/
│   ├── kafka/
│   ├── postgres/
│   ├── redis/
│   └── observability/
│
├── migrations/
│
├── scripts/
│   ├── dev/
│   ├── test/
│   ├── security/
│   └── release/
│
├── configs/
│   ├── development/
│   ├── staging/
│   └── production/
│
└── .github/
    ├── workflows/
    │   ├── ci.yml
    │   ├── security.yml
    │   ├── performance.yml
    │   └── release.yml
    │
    ├── ISSUE_TEMPLATE/
    └── PULL_REQUEST_TEMPLATE.md
```

---

# 55. DEVELOPMENT PHASES

Build SENTINEL sequentially.

Do not attempt to build the entire production platform in one uncontrolled operation.

---

## PHASE 0 — FOUNDATION

Implement:

- Repository
- Python project
- Dependency management
- Basic configuration
- Logging
- Initial documentation
- Test framework
- CI foundation

Commit:

```text
chore: initialize SENTINEL enterprise repository
```

Tag:

```text
v0.1.0-foundation
```

---

## PHASE 1 — STATE MACHINE

Implement:

- Transaction entity
- Transaction states
- State transitions
- Transition validation
- State history

Commit:

```text
feat: implement transaction state machine
```

Tag:

```text
v0.2.0-phase-01
```

---

## PHASE 2 — INTEGRITY ENGINE

Implement:

- Transaction validation
- Financial invariants
- Duplicate detection
- Integrity decisions

Commit:

```text
feat: implement transaction integrity engine
```

Tag:

```text
v0.3.0-phase-02
```

---

## PHASE 3 — BALANCE ANOMALY

Implement:

- Expected balance effect
- Observed balance
- Balance consistency
- Balance anomaly detection

Commit:

```text
feat: implement balance anomaly detection engine
```

Tag:

```text
v0.4.0-phase-03
```

---

## PHASE 4 — RISK ENGINE

Implement:

- Risk factors
- Risk scoring
- Rule evaluation
- Decision records

Commit:

```text
feat: implement transaction risk engine
```

Tag:

```text
v0.5.0-phase-04
```

---

## PHASE 5 — PROTECTIVE RESPONSE

Implement:

- Allow
- Reject
- Hold
- Review
- Block retry
- Reconciliation trigger
- Protective action audit

Commit:

```text
feat: implement protective response engine
```

Tag:

```text
v0.6.0-phase-05
```

---

## PHASE 6 — CBS ADAPTERS

Implement:

- CBS interface
- Simulator adapter
- Status query
- Balance query
- Reversal interface

Commit:

```text
feat: implement CBS adapter framework
```

Tag:

```text
v0.7.0-phase-06
```

---

## PHASE 7 — ORCHESTRATION

Implement:

- Transaction workflow
- Dependency coordination
- Failure handling
- Retry policy
- Timeout handling
- UNKNOWN state handling

Commit:

```text
feat: implement transaction orchestration layer
```

Tag:

```text
v0.8.0-phase-07
```

---

## PHASE 8 — POSTGRESQL

Implement:

- Database models
- Migrations
- Repository layer
- Transaction persistence
- Idempotency persistence

Commit:

```text
feat: implement PostgreSQL persistence layer
```

Tag:

```text
v0.9.0-phase-08
```

---

## PHASE 9 — REDIS

Implement:

- Cache
- Coordination
- Rate limiting
- Fast idempotency lookup

Commit:

```text
feat: implement distributed transaction coordination
```

Tag:

```text
v0.10.0-phase-09
```

---

## PHASE 10 — KAFKA

Implement:

- Event schemas
- Producers
- Consumers
- Idempotent consumption
- Dead-letter handling

Commit:

```text
feat: implement transaction event streaming
```

Tag:

```text
v0.11.0-phase-10
```

---

## PHASE 11 — RECONCILIATION

Implement:

- Reconciliation engine
- UNKNOWN handling
- Partial failure detection
- Reversal workflows
- Compensation workflows
- Manual review

Commit:

```text
feat: implement transaction reconciliation engine
```

Tag:

```text
v0.12.0-phase-11
```

---

## PHASE 12 — ENTERPRISE API

Implement:

- Versioned API
- Authentication
- Authorization
- Error taxonomy
- Correlation IDs
- Idempotency headers
- Status endpoints

Commit:

```text
feat: implement enterprise transaction APIs
```

Tag:

```text
v0.13.0-phase-12
```

---

## PHASE 13 — SECURITY

Implement:

- mTLS architecture
- IAM
- RBAC
- Secrets integration
- Certificate management
- Secure configuration

Commit:

```text
security: implement enterprise security controls
```

Tag:

```text
v0.14.0-phase-13
```

---

## PHASE 14 — AUDIT

Implement:

- Audit records
- Tamper-evident design
- Administrative audit
- Decision traceability

Commit:

```text
feat: implement immutable transaction audit architecture
```

Tag:

```text
v0.15.0-phase-14
```

---

## PHASE 15 — OBSERVABILITY

Implement:

- Metrics
- Logging
- Tracing
- Dashboards
- Alerts
- UNKNOWN monitoring
- Reconciliation monitoring

Commit:

```text
feat: implement enterprise observability stack
```

Tag:

```text
v0.16.0-phase-15
```

---

## PHASE 16 — PERFORMANCE

Implement:

- Load tests
- Concurrency tests
- Benchmarking
- Capacity measurement

Commit:

```text
test: implement performance and concurrency benchmarks
```

Tag:

```text
v0.17.0-phase-16
```

---

## PHASE 17 — FAULT INJECTION

Implement:

- Dependency failure
- Network failure
- Service crash
- Duplicate events
- Out-of-order events
- Partial transaction scenarios

Commit:

```text
test: implement fault injection and resilience testing
```

Tag:

```text
v0.18.0-phase-17
```

---

## PHASE 18 — KUBERNETES

Implement:

- Kubernetes manifests
- Helm
- Configurations
- Scaling
- Health checks
- Deployment strategy

Commit:

```text
feat: implement Kubernetes deployment architecture
```

Tag:

```text
v0.19.0-phase-18
```

---

## PHASE 19 — HA / DR

Implement:

- High availability
- Failover
- Backup
- Restore
- DR procedures
- Recovery testing

Commit:

```text
feat: implement high availability and disaster recovery
```

Tag:

```text
v0.20.0-phase-19
```

---

## PHASE 20 — BANK SIMULATOR

Implement:

- CBS simulator
- Payment simulation
- Failure scenarios
- Transaction scenarios
- Fraud/anomaly generation

Commit:

```text
test: implement bank integration simulation environment
```

Tag:

```text
v0.21.0-phase-20
```

---

## PHASE 21 — SECURITY VALIDATION

Run:

- SAST
- DAST
- Dependency scan
- Secret scan
- Container scan
- Security tests

Commit:

```text
test: complete enterprise security validation
```

Tag:

```text
v0.22.0-phase-21
```

---

## PHASE 22 — PRODUCTION HARDENING

Fix:

- Performance findings
- Security findings
- Reliability findings
- Observability gaps
- Documentation gaps
- Deployment problems

Commit:

```text
fix: address production readiness findings
```

Tag:

```text
v0.23.0-phase-22
```

---

## PHASE 23 — FINAL ACCEPTANCE

Document:

- Architecture acceptance
- Test acceptance
- Security acceptance
- Performance acceptance
- Operational acceptance

Commit:

```text
docs: record final enterprise acceptance
```

---

## PHASE 24 — RELEASE CANDIDATE

Tag:

```text
v1.0.0-rc1
```

---

## PHASE 25 — PRODUCTION RELEASE

Tag:

```text
v1.0.0
```

---

# 56. PHASE GATE

Every phase MUST follow:

```text
IMPLEMENT
   ↓
UNIT TEST
   ↓
INTEGRATION TEST
   ↓
SECURITY CHECK
   ↓
ARCHITECTURE REVIEW
   ↓
FAILURE TEST
   ↓
DOCUMENT
   ↓
FIX FINDINGS
   ↓
FINAL VALIDATION
   ↓
COMMIT
   ↓
TAG
   ↓
NEXT PHASE
```

Never skip a gate.

Never proceed with unresolved critical failures.

---

# 57. GIT RULES

Use meaningful commits.

Do not create commits such as:

```text
update
changes
fix stuff
test
final
new
```

Use structured commits such as:

```text
feat:
fix:
test:
security:
docs:
refactor:
chore:
perf:
```

Each completed phase must have:

1. Passing tests
2. Review
3. Clean working tree
4. Commit
5. Tag

---

# 58. CODE QUALITY

Code must be:

- Typed
- Modular
- Testable
- Documented
- Secure
- Observable
- Maintainable

Prefer:

```text
dependency injection
interfaces
protocols
small services
explicit domain models
immutable value objects where appropriate
structured errors
```

Avoid:

```text
global mutable state
hidden side effects
god classes
god functions
hard-coded credentials
hard-coded bank behavior
magic numbers
silent exception handling
```

---

# 59. ERROR HANDLING

Never silently swallow exceptions.

Bad:

```python
try:
    ...
except Exception:
    pass
```

Instead:

- Log safely
- Preserve context
- Map to structured error
- Maintain transaction state
- Trigger recovery if required
- Avoid leaking sensitive information

---

# 60. LOGGING

Use structured logging.

Every transaction-related operation should support:

```text
transaction_id
request_id
correlation_id
trace_id
service
timestamp
event
result
```

Never log secrets or unnecessary sensitive data.

---

# 61. CONFIGURATION

Configuration must be externalized.

Use environment/configuration management.

Never hard-code:

```text
database passwords
API keys
private keys
production endpoints
TLS secrets
```

Provide:

```text
.env.example
```

with safe placeholders only.

---

# 62. CI/CD

Create CI pipelines for:

```text
lint
format
type checking
unit tests
integration tests
security scans
dependency scans
container scans
performance checks where appropriate
```

Production deployment must require controlled approval.

---

# 63. DEPENDENCY MANAGEMENT

Every dependency must have a reason.

Avoid unnecessary packages.

Before adding a dependency:

1. Check whether the standard library already solves the problem.
2. Check project maintenance status.
3. Check known vulnerabilities.
4. Check license compatibility.
5. Check transitive dependencies.
6. Document why it is required.

---

# 64. DATABASE SAFETY

Financial persistence must use database transactions correctly.

Be careful with:

- Race conditions
- Lost updates
- Duplicate inserts
- Concurrent transaction processing
- Isolation levels
- Unique constraints

Idempotency must be enforced at the durable-storage level where appropriate.

---

# 65. CONCURRENCY

Assume concurrent requests will occur.

Test:

```text
Same transaction submitted twice
Same idempotency key concurrently
Two workers process same event
Two reconciliation workers process same case
Duplicate Kafka event
```

The system must remain financially safe.

---

# 66. NO BLIND ASSUMPTIONS

Do not assume:

```text
timeout = failure
HTTP 200 = financial success
HTTP error = financial failure
Kafka delivery = transaction completion
Redis state = financial truth
cached balance = authoritative balance
ML anomaly = confirmed fraud
```

Always distinguish technical response from financial state.

---

# 67. TECHNICAL RESPONSE VS FINANCIAL OUTCOME

A key design requirement is to separate:

```text
Transport Outcome
```

from:

```text
Financial Outcome
```

Example:

```text
HTTP timeout
≠
Financial failure
```

The correct state may be:

```text
UNKNOWN
```

until CBS state is verified.

---

# 68. TRANSACTION DECISION RECORD

Every transaction decision should be reproducible.

Record:

```text
transaction_id
decision_id
decision
risk_score
rules_triggered
policy_version
configuration_version
model_version
timestamp
```

---

# 69. SCHEMA VERSIONING

Events and APIs must be versioned.

Examples:

```text
schema_version: 1
api_version: v1
```

Never make breaking schema changes without a controlled migration strategy.

---

# 70. BACKWARD COMPATIBILITY

Prefer backward-compatible evolution.

For Kafka:

- New optional fields
- Versioned schemas
- Compatibility testing

For APIs:

- Versioned endpoints
- Deprecation policy
- Compatibility documentation

---

# 71. DOCUMENTATION REQUIREMENTS

Maintain:

```text
README.md
Architecture documentation
ADR documents
Security documentation
Threat model
Runbooks
SLO/SLI documentation
DR documentation
Capacity planning
Integration contracts
```

Code changes that affect architecture must update documentation.

---

# 72. ARCHITECTURE DECISION RECORDS

Create ADRs for major decisions.

At minimum:

```text
ADR-001-cbs-authority.md
ADR-002-idempotency-semantics.md
ADR-003-event-delivery-semantics.md
```

Additional ADRs should be created when major architecture decisions occur.

---

# 73. DO NOT OVERENGINEER EARLY

During early phases:

Do not implement unnecessary distributed complexity before it is required.

Build:

```text
correct domain
correct state machine
correct integrity rules
correct tests
```

before adding:

```text
Kafka
Kubernetes
ML
multi-region
```

The architecture must grow progressively.

---

# 74. DO NOT UNDERENGINEER THE FINANCIAL CORE

Even during early development, never simplify financial logic in a way that creates unsafe semantics.

Do not use:

```text
random transaction IDs
in-memory financial truth
fake balances
blind retries
unvalidated state transitions
```

unless they exist strictly inside the simulator/test environment and are clearly identified.

---

# 75. BANK SIMULATOR VS PRODUCTION

The simulator may simplify infrastructure.

Production architecture must not.

Simulator:

```text
Safe
Deterministic
Testable
Fault-injectable
```

Production:

```text
Secure
Durable
Highly available
Auditable
Recoverable
Observable
```

---

# 76. DEVELOPMENT ENVIRONMENT

The project must be easy to start locally.

Provide:

```text
Makefile
Docker Compose
.env.example
README
Development scripts
Database migration commands
Test commands
```

A developer should be able to start the development environment with documented commands.

---

# 77. LOCAL DEVELOPMENT TARGET

The development environment should eventually support:

```text
SENTINEL API
PostgreSQL
Redis
Kafka
Kafka consumer
CBS simulator
Prometheus
Grafana
```

Use Docker Compose for local infrastructure where practical.

---

# 78. PRODUCTION ENVIRONMENT

Production should support:

```text
Kubernetes
PostgreSQL HA strategy
Redis HA strategy
Kafka cluster
Secret management
Certificate management
Monitoring
Logging
Tracing
Backup
DR
```

Do not assume local Docker Compose equals production architecture.

---

# 79. SECURITY SCANNING

Integrate appropriate tools.

Examples:

```text
Ruff
MyPy
Bandit
pip-audit
Trivy
Gitleaks
Semgrep
```

Use tools appropriate to the final technology stack.

Do not add tools merely for appearance.

---

# 80. SBOM

Generate a Software Bill of Materials during production hardening.

Track:

- Dependencies
- Versions
- Licenses
- Vulnerabilities

---

# 81. SUPPLY-CHAIN SECURITY

Protect:

```text
Source code
Dependencies
CI/CD
Container images
Build artifacts
Deployment manifests
Secrets
```

Use pinned/reproducible dependencies where practical.

---

# 82. INCIDENT RESPONSE

Create runbooks for:

```text
CBS outage
Transaction timeout spike
Unknown transaction surge
Balance mismatch
Kafka outage
Database outage
Redis outage
Security incident
Credential compromise
Certificate expiration
Reconciliation backlog
Circuit breaker activation
```

---

# 83. OPERATIONAL RUNBOOK PRINCIPLE

Every critical alert must answer:

```text
What happened?
How do I verify it?
What is the impact?
What should I do?
What must I NOT do?
How do I recover?
How do I verify recovery?
```

---

# 84. PRODUCTION READINESS

Before v1.0, verify:

## Architecture

- CBS authority confirmed
- Adapters implemented
- State machine validated
- Idempotency validated
- Reconciliation validated

## Financial Integrity

- Debit/credit consistency
- Duplicate prevention
- UNKNOWN handling
- Partial failure handling
- Reversal handling

## Security

- Authentication
- Authorization
- mTLS
- Secrets
- Certificates
- Encryption
- Audit
- Threat model

## Reliability

- HA
- Failover
- Circuit breakers
- Timeouts
- Backpressure
- DR
- Backup/restore

## Observability

- Metrics
- Logs
- Traces
- Dashboards
- Alerts
- UNKNOWN monitoring

## Testing

- Unit
- Integration
- Contract
- E2E
- Performance
- Concurrency
- Fault injection
- Security

## Operations

- Runbooks
- SLOs
- DR
- Capacity planning
- Incident response

---

# 85. AI CODING AGENT BEHAVIOR

While working in VS Code:

## Before modifying code

Inspect:

```text
repository structure
existing source files
tests
configuration
documentation
git status
```

Never overwrite working code blindly.

---

## Before adding a dependency

Check whether it is necessary.

---

## Before changing architecture

Explain:

```text
Problem
Current behavior
Proposed change
Impact
Testing strategy
```

Then implement when appropriate.

---

## After every meaningful implementation

Run relevant tests.

At minimum:

```text
unit tests
lint
type checks
```

For integration changes:

```text
integration tests
```

For financial transaction changes:

```text
transaction scenario tests
concurrency tests
idempotency tests
```

---

# 86. SELF-REVIEW REQUIREMENT

After implementation, review your own work as if you were:

### Senior Banking Architect

Ask:

> Could this create an incorrect financial effect?

### Security Engineer

Ask:

> Could this be abused?

### Distributed Systems Engineer

Ask:

> What happens when dependencies fail?

### QA Engineer

Ask:

> What happens under concurrency?

### SRE

Ask:

> Can operations detect and recover this failure?

### Auditor

Ask:

> Can we prove what happened?

Fix identified problems before continuing.

---

# 87. NEVER CLAIM SUCCESS WITHOUT EVIDENCE

Do not say:

```text
Production ready
Secure
High performance
Exactly once
Highly available
Fully compliant
```

unless there is evidence.

Instead state:

```text
Implemented
Tested
Measured
Verified
Not yet verified
```

Performance and security claims must be evidence-based.

---

# 88. COMPLIANCE PRINCIPLE

Do not claim that referencing a framework automatically means compliance.

Potential reference frameworks include:

```text
NIST CSF
ISO/IEC 27001
PCI DSS where applicable
Basel operational resilience principles
Applicable Ethiopian financial-sector requirements
```

Actual compliance requires appropriate organizational, legal, regulatory, and security assessment.

---

# 89. ETHIOPIAN BANKING CONTEXT

The architecture should be suitable for eventual integration into banking environments in Ethiopia.

However:

Do not hard-code assumptions about a specific Ethiopian bank.

Use:

```text
Bank Adapter
Payment Switch Adapter
Configurable Policies
Configurable Limits
Configurable Regulatory Rules
```

Bank-specific requirements must remain configurable and contract-driven.

---

# 90. CORE QUALITY PRINCIPLE

When forced to choose:

```text
Correctness > Convenience
Safety > Speed
Explicit state > Hidden behavior
Durability > Memory
Authoritative data > Cache
Deterministic integrity > ML prediction
Auditable behavior > opaque behavior
Tested behavior > assumed behavior
```

---

# 91. FINAL SYSTEM ARCHITECTURE

The final architecture should conceptually be:

```text
                         BANKING CHANNELS
                                │
                                ▼
                         API / GATEWAY
                                │
                                ▼
                 ┌────────────────────────────┐
                 │          SENTINEL          │
                 │                            │
                 │ Transaction Integrity      │
                 │ Balance Integrity          │
                 │ Idempotency                │
                 │ State Machine              │
                 │ Transaction Journal        │
                 │ Risk Engine                │
                 │ Policy Engine              │
                 │ Rule Engine                │
                 │ Anomaly Detection          │
                 │ ML Analytics               │
                 │ Reconciliation             │
                 │ Protective Response        │
                 │ Audit                      │
                 │ Observability              │
                 └──────────────┬─────────────┘
                                │
                                ▼
                         CBS ADAPTER
                                │
                                ▼
                     CORE BANKING SYSTEM
                                │
                                ▼
                             LEDGER


             ┌────────────────────────────────┐
             │        EVENT PLATFORM          │
             │             Kafka              │
             └───────────────┬────────────────┘
                             │
             ┌───────────────┼─────────────────┐
             ▼               ▼                 ▼
        Risk / ML          Audit             SOC/NOC
        Analytics          Pipeline          Monitoring


     PostgreSQL → Durable SENTINEL State
     Redis      → Coordination / Cache
     Kubernetes → Deployment / Scaling
     Prometheus → Metrics
     Grafana    → Dashboards
     OpenTelemetry → Tracing
```

---

# 92. FINAL BUILD OBJECTIVE

At completion, SENTINEL must provide a production-oriented platform capable of:

```text
Receive transaction
       ↓
Validate transaction
       ↓
Check idempotency
       ↓
Validate integrity
       ↓
Evaluate risk
       ↓
Apply policy
       ↓
Submit safely to CBS
       ↓
Track authoritative state
       ↓
Detect anomalies
       ↓
Detect partial failures
       ↓
Handle UNKNOWN states
       ↓
Reconcile
       ↓
Reverse/compensate when approved
       ↓
Record audit
       ↓
Publish events
       ↓
Expose observability
```

The final system must be able to answer:

> **What happened to this transaction?**

with evidence.

It must be able to answer:

> **Was the source account debited?**

with authoritative evidence.

It must be able to answer:

> **Was the destination credited?**

with authoritative evidence.

It must be able to answer:

> **Was this transaction processed more than once?**

through durable idempotency and transaction history.

It must be able to answer:

> **Why was this transaction blocked, allowed, reconciled, reversed, or escalated?**

through auditable decision records.

---

# 93. FINAL COMMAND TO THE AI AGENT

Build SENTINEL systematically.

Do not skip phases.

Do not fabricate functionality.

Do not claim untested behavior.

Do not introduce unsafe financial semantics.

Do not treat the cache as financial truth.

Do not blindly retry UNKNOWN transactions.

Do not allow duplicate financial effects.

Do not allow ML to override deterministic financial integrity.

Do not tightly couple the domain to one bank or CBS implementation.

Do not move to the next phase while critical tests or architecture checks are failing.

Always:

```text
INSPECT
→ DESIGN
→ IMPLEMENT
→ TEST
→ REVIEW
→ FIX
→ DOCUMENT
→ COMMIT
→ TAG
→ PROCEED
```

The ultimate objective is:

> **A secure, auditable, highly reliable, observable, scalable, bank-integratable transaction-integrity and anomaly-prevention control plane that protects financial transaction correctness while leaving the existing CBS as the authoritative financial system.**

# END OF MASTER BUILD PROMPT