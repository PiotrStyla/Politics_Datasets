from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).with_name("build_kultura_bez_barier_pl.py")
spec = importlib.util.spec_from_file_location("builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_catalog_license_evidence_requires_authorship_and_license():
    html = "<p>Publikacje autorstwa Fundacji Kultury bez Barier. Oddajemy je na licencji Creative Commons (CC BY-SA 3.0).</p>"
    evidence = builder.catalog_license_evidence(html)
    assert "CC BY-SA 3.0" in evidence


def test_catalog_license_evidence_rejects_noncommercial_marker():
    html = "<p>Publikacje autorstwa Fundacji Kultury bez Barier. CC BY-SA 3.0. CC BY-NC.</p>"
    try:
        builder.catalog_license_evidence(html)
    except ValueError as error:
        assert "noncommercial" in str(error)
    else:
        raise AssertionError("expected noncommercial marker rejection")


def test_repair_wrapped_text_is_deterministic():
    pages = ["1\nTo jest zda-\nnie testowe\nz dalszym ciagiem.\n\nNowy akapit."]
    assert builder.repair_wrapped_text(pages) == "To jest zdanie testowe z dalszym ciagiem.\n\nNowy akapit."
