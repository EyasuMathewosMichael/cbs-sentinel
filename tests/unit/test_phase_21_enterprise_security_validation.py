from pathlib import Path


def test_phase_21_enterprise_security_validation_artifacts_exist():
    repo_root = Path(__file__).resolve().parents[2]
    security_dir = repo_root / "deployments" / "security_validation"
    readme = security_dir / "README.md"
    scan_report = security_dir / "enterprise_security_validation_report.md"

    assert readme.exists(), "Phase 21 security validation artifact README is required"
    assert scan_report.exists(), "Phase 21 security validation scan report is required"

    readme_text = readme.read_text(encoding="utf-8")
    report_text = scan_report.read_text(encoding="utf-8")

    required_topics = {
        "SAST",
        "DAST",
        "Dependency scan",
        "Container scan",
        "Secret scan",
        "SBOM",
        "API security testing",
        "Authorization testing",
        "TLS testing",
        "Penetration-testing preparation",
    }

    for topic in required_topics:
        assert topic.lower() in readme_text.lower() or topic.lower() in report_text.lower()
