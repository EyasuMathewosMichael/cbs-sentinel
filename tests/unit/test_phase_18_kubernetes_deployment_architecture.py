from decimal import Decimal
from pathlib import Path

from sentinel.domain.integrity import (
    DuplicateRegistry,
    IntegrityDecisionCode,
    IntegrityEngine,
    TransactionRequest,
)


def test_phase_18_kubernetes_deployment_artifacts_exist():
    repo_root = Path(__file__).resolve().parents[2]
    base = repo_root / "deployments" / "kubernetes" / "base"
    overlays = repo_root / "deployments" / "kubernetes" / "overlays"
    helm = repo_root / "deployments" / "helm" / "sentinel"

    assert (base / "kustomization.yaml").exists()
    assert (base / "sentinel-deployment.yaml").exists()
    assert (base / "sentinel-service.yaml").exists()
    assert (base / "sentinel-hpa.yaml").exists()
    assert (base / "sentinel-pdb.yaml").exists()
    assert (base / "sentinel-network-policy.yaml").exists()
    assert (base / "sentinel-secret.yaml").exists()
    assert (base / "sentinel-tls-secret.yaml").exists()

    assert (overlays / "dev" / "kustomization.yaml").exists()
    assert (overlays / "staging" / "kustomization.yaml").exists()
    assert (overlays / "production" / "kustomization.yaml").exists()

    assert (helm / "Chart.yaml").exists()
    assert (helm / "values.yaml").exists()
    assert (helm / "templates" / "deployment.yaml").exists()
    assert (helm / "templates" / "service.yaml").exists()
    assert (helm / "templates" / "hpa.yaml").exists()
    assert (helm / "templates" / "pdb.yaml").exists()
    assert (helm / "templates" / "networkpolicy.yaml").exists()


def test_phase_18_kubernetes_deployment_contract_carries_probe_and_balance_guards():
    deployment = Path("deployments/kubernetes/base/sentinel-deployment.yaml").read_text(
        encoding="utf-8"
    )
    assert "readinessProbe:" in deployment
    assert "livenessProbe:" in deployment
    assert "startupProbe:" in deployment
    assert "RollingUpdate" in deployment
    assert "podAntiAffinity" in deployment
    assert "resources:" in deployment

    request = TransactionRequest(
        transaction_id="txn-race-001",
        idempotency_key="idem-race-001",
        source_account="100",
        destination_account="200",
        amount=Decimal("10.00"),
        currency="USD",
        transaction_type="TRANSFER",
    )
    engine = IntegrityEngine(DuplicateRegistry())

    first = engine.evaluate(request)
    second = engine.evaluate(request)

    assert first.code is IntegrityDecisionCode.ALLOW
    assert second.code is IntegrityDecisionCode.DUPLICATE_TRANSACTION
    assert second.reasons == ("duplicate_transaction",)
