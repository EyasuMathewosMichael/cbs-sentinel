from pathlib import Path


def test_phase_22_production_readiness_review_artifacts_exist():
    repo_root = Path(__file__).resolve().parents[2]
    readiness_dir = repo_root / "deployments" / "production_readiness"
    readme = readiness_dir / "README.md"
    report = readiness_dir / "production_readiness_findings_report.md"

    assert readme.exists(), "Phase 22 production-readiness artifact README is required"
    assert report.exists(), "Phase 22 production-readiness findings report is required"

    readme_text = readme.read_text(encoding="utf-8")
    report_text = report.read_text(encoding="utf-8")

    required_topics = {
        "architecture",
        "financial integrity",
        "security",
        "performance",
        "reliability",
        "observability",
        "DR",
        "operations",
        "testing",
        "documentation",
        "deployment",
        "rollback",
        "configuration",
        "bank integration",
        "findings",
    }

    for topic in required_topics:
        assert topic.lower() in readme_text.lower() or topic.lower() in report_text.lower()
