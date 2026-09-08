import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_rock_pollub_pl.py")
SPEC = importlib.util.spec_from_file_location("build_rock_pollub_pl", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalize_repairs_hyphenation_and_pages():
    assert MODULE.normalize("Pierw-\nszy akapit.\n12\n\ndrugi wiersz") == "Pierwszy akapit.\n\ndrugi wiersz"


def test_candidate_is_fail_closed():
    valid = {"metadata": {"dc.rights": [{"value": "CC-BY-SA-4.0"}], "dc.language": [{"value": "pl"}],
                          "dc.subtype": [{"value": "Handbook"}], "dc.type": [{"value": "Book"}]}}
    assert MODULE.candidate(valid)
    for key in ("dc.rights", "dc.language", "dc.subtype", "dc.type"):
        broken = {"metadata": dict(valid["metadata"])}
        broken["metadata"].pop(key)
        assert not MODULE.candidate(broken)


def test_shingles_are_deterministic():
    text = "jeden dwa trzy cztery pięć sześć"
    assert MODULE.shingles(text) == {"jeden dwa trzy cztery pięć", "dwa trzy cztery pięć sześć"}


def test_title_normalization_is_case_and_diacritic_insensitive():
    assert MODULE.normalize_title("Ćwiczenia: Łódź") == "cwiczenia łodz"


def test_pilot_pdf_limit_is_bounded():
    assert MODULE.MAX_PDF_BYTES == 50 * 1024 * 1024
