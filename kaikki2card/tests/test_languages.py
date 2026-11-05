import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import languages as L  # noqa: E402


def test_tokenize_keeps_irish_hyphen_and_elision():
    text = "D'fhág sé an t-athair. Bhí 3 cat ann, n-aon!"
    assert L.tokenize(text) == ["D'fhág", "sé", "an", "t-athair", "Bhí", "cat", "ann", "n-aon"]


def test_unknown_language_uses_default():
    fn = L.get_candidates_fn("xx")
    assert fn("Eau") == ["Eau", "eau"]


def test_irish_token_itself_comes_first():
    assert L.irish_candidates("bean")[0] == "bean"
    assert L.irish_candidates("Bean")[:2] == ["Bean", "bean"]


def test_irish_lenition():
    assert "bean" in L.irish_candidates("bhean")
    assert "súil" in L.irish_candidates("shúil")
    assert "teach" in L.irish_candidates("theach")
    assert "fear" in L.irish_candidates("fhear")


def test_irish_eclipsis():
    cands = {
        "mbád": "bád", "gcat": "cat", "ndoras": "doras",
        "bhfear": "fear", "ngort": "gort", "bpáiste": "páiste", "dteach": "teach",
    }
    for surface, base in cands.items():
        assert base in L.irish_candidates(surface), surface


def test_irish_prothesis():
    assert "athair" in L.irish_candidates("t-athair")
    assert "athair" in L.irish_candidates("hathair")
    assert "aon" in L.irish_candidates("n-aon")
    assert "súil" in L.irish_candidates("tsúil")


def test_irish_elision_then_lenition():
    assert "fág" in L.irish_candidates("d'fhág")
    assert "fág" in L.irish_candidates("d’fhág")  # typographic apostrophe
    assert "athair" in L.irish_candidates("m'athair")


def test_irish_candidates_are_unique():
    cands = L.irish_candidates("bhean")
    assert len(cands) == len(set(cands))
