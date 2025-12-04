from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_backend_dockerfile_multistage():
    dockerfile = (_repo_root() / "deploy" / "backend.Dockerfile").read_text().splitlines()
    from_lines = [line for line in dockerfile if line.startswith("FROM ")]
    assert len(from_lines) >= 2, "Dockerfile must use multi-stage build"
    assert any("AS builder" in line for line in from_lines), "Builder stage missing"
    assert any("AS runner" in line for line in from_lines), "Runner stage missing"


def test_promotion_pipeline_has_required_stages():
    promotion = (_repo_root() / "deploy" / "promotion.yaml").read_text()
    for stage in ["build", "verify", "canary", "promote"]:
        assert f"name: {stage}" in promotion
    assert "pytest --cov=app" in promotion
    assert "promote_release.py --canary-check" in promotion

