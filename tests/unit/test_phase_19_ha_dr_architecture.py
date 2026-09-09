from pathlib import Path


def test_phase_19_ha_dr_architecture_contract_exists():
    repo_root = Path(__file__).resolve().parents[2]
    ha_dr = repo_root / "deployments" / "ha_dr"

    assert (ha_dr / "README.md").exists()
    assert (ha_dr / "rpo_rto.md").exists()
    assert (ha_dr / "backup_restore.md").exists()
    assert (ha_dr / "failover_failback.md").exists()
    assert (ha_dr / "site_failure.md").exists()
    assert (ha_dr / "disaster_recovery_review.md").exists()

    readme = (ha_dr / "README.md").read_text(encoding="utf-8")
    assert "RPO" in readme
    assert "RTO" in readme
    assert "backup" in readme.lower()
    assert "restore" in readme.lower()
    assert "failover" in readme.lower()
    assert "failback" in readme.lower()
    assert "site failure" in readme.lower()

    rpo_rto = (ha_dr / "rpo_rto.md").read_text(encoding="utf-8")
    assert "RPO" in rpo_rto
    assert "RTO" in rpo_rto
    assert "seconds" in rpo_rto.lower() or "minutes" in rpo_rto.lower()

    backup_restore = (ha_dr / "backup_restore.md").read_text(encoding="utf-8")
    assert "backup" in backup_restore.lower()
    assert "restore" in backup_restore.lower()

    failover_failback = (ha_dr / "failover_failback.md").read_text(encoding="utf-8")
    assert "failover" in failover_failback.lower()
    assert "failback" in failover_failback.lower()

    site_failure = (ha_dr / "site_failure.md").read_text(encoding="utf-8")
    assert "site failure" in site_failure.lower()
    assert "DNS" in site_failure or "route" in site_failure.lower()

    review = (ha_dr / "disaster_recovery_review.md").read_text(encoding="utf-8")
    required_review_phrases = (
        "database failure",
        "node failure",
        "service failure",
        "Kubernetes failure",
        "site failure",
        "recovery",
        "idempotency",
        "financial effect",
        "duplicate financial effect",
    )
    for phrase in required_review_phrases:
        assert phrase.lower() in review.lower()

    assert "no duplicate financial effect" in review.lower()
    assert "transaction_id" in review.lower()
    assert "idempotency_key" in review.lower()
