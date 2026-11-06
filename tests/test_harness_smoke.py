from harness.models import ActionRequest, Target
from harness.harness import HarnessConfig, RaphaelHarness


def test_harness_rejects_out_of_scope_action() -> None:
    config = HarnessConfig(dry_run=True, target_host="authorized.example", authorized_scopes=("authorized.example",))
    harness = RaphaelHarness(config)

    async def exercise() -> None:
        await harness.start()
        decision = await harness.submit(
            ActionRequest(
                action_type="scope_check",
                target=Target(host="other.example", scope=()),
                rationale="test",
                metadata={},
            )
        )
        assert decision["approved"] is False
        await harness.stop()

    import asyncio

    asyncio.run(exercise())


def test_research_bundle_normalization() -> None:
    from src.harness.research import BundleNormalizer

    bundle = BundleNormalizer().normalize(
        "scihub",
        "https://sci-hub.se/example",
        {"title": "Test Paper", "authors": [" researcher "], "abstract": "x", "text": "CVE-2024-1234"},
    )
    assert bundle.title == "Test Paper"
    assert bundle.cves == ["CVE-2024-1234"]