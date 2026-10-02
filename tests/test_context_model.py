import pytest
from pydantic import ValidationError

from packages.context_optimizer import (
    ContextBudget, ContextCache, ContextCompressor, ContextProvenance,
    ContextRanker, RepoFileIndex, RepositoryIndexer,
)
from packages.model_router import (
    MockNebiusProvider, ModelProvider, ModelRequest, ModelRouter,
)

SAMPLE = RepoFileIndex(
    path="apps/api/main.py", language="python", size=1024, hash="a1b2c3d4",
    imports=["fastapi"], symbols=["app"], tests=["tests/unit/test_api.py"],
)


def test_models():
    assert SAMPLE.hash == "a1b2c3d4" and SAMPLE.symbols == ["app"]
    budget = ContextBudget(max_input_tokens=50000, max_output_tokens=12000)
    assert budget.max_total_tokens == 62000
    prov = ContextProvenance(source_type="repo", file_path="main.py", trust_level="trusted")
    assert prov.trust_level == "trusted"
    with pytest.raises(ValidationError):
        SAMPLE.path = "mutated.py"


def test_mock_nebius_provider():
    res = MockNebiusProvider().generate(
        ModelRequest(prompt="Analyze context", model_name="nemotron-super", max_tokens=150)
    )
    assert res.model_used == "nemotron-super"
    assert res.total_tokens == res.prompt_tokens + res.completion_tokens > 0
    assert res.provenance.trust_level == "untrusted"


@pytest.mark.parametrize("factory", [
    lambda: ContextBudget(max_input_tokens=-1, max_output_tokens=5),
    lambda: ModelRequest(prompt="x", model_name="m", max_tokens=0),
    lambda: RepoFileIndex(path="p", language="x", size=-5, hash="h"),
    lambda: ContextProvenance(source_type="repo", file_path="f", trust_level="maybe"),
])
def test_validation(factory):
    with pytest.raises(ValidationError):
        factory()


def test_interfaces_are_abstract():
    for iface in (RepositoryIndexer, ContextRanker, ContextCompressor, ContextCache, ModelProvider, ModelRouter):
        with pytest.raises(TypeError):
            iface()


def test_interfaces_are_implementable():
    class Ranker(ContextRanker):
        def rank(self, index_entries, query):
            return sorted(index_entries, key=lambda e: e.path)

    class Compressor(ContextCompressor):
        def compress(self, index_entries, budget):
            return "\n".join(e.path for e in index_entries)

    class Cache(ContextCache):
        def __init__(self):
            self.d = {}

        def get(self, key):
            return self.d.get(key)

        def set(self, key, value):
            self.d[key] = value

    class Router(ModelRouter):
        def select_model(self, task_complexity):
            return {"simple": "nemotron-nano", "complex": "nemotron-ultra"}[task_complexity]

    entries = [RepoFileIndex(path=p, language="python", size=1, hash="h") for p in ("b.py", "a.py")]
    budget = ContextBudget(max_input_tokens=500, max_output_tokens=100)
    assert [e.path for e in Ranker().rank(entries, "q")] == ["a.py", "b.py"]
    assert Compressor().compress(entries, budget) == "b.py\na.py"
    cache = Cache()
    assert cache.get("k") is None
    cache.set("k", {"v": 1})
    assert cache.get("k") == {"v": 1}
    assert Router().select_model("complex") == "nemotron-ultra"


if __name__ == "__main__":
    import pytest as _pytest

    raise SystemExit(_pytest.main([__file__, "-q"]))
