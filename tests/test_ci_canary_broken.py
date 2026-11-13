"""Throwaway branch only: a deliberately failing test to prove CI blocks the image build."""


def test_deliberately_broken() -> None:
    assert False, "deliberate failure (P1-1a CI gate check)"
