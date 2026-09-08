import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("build_ted_pl.py")
SPEC = importlib.util.spec_from_file_location("build_ted_pl", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_normalize_and_redact():
    text, counts = MODULE.redact_pii("Kontakt: anna@example.pl, tel. +48 123 456 789, NIP 123-456-32-18")
    assert "anna@example.pl" not in text
    assert "123 456 789" not in text
    assert "123-456-32-18" not in text
    assert counts["email"] == counts["phone"] == counts["national_id"] == 1


def test_phone_redaction_does_not_mask_cpv_code():
    text, counts = MODULE.redact_pii("Kod CPV 33141320-9, telefon 123456789.")
    assert "33141320-9" in text
    assert "123456789" not in text
    assert counts["phone"] == 1


def test_parse_official_xml_pilot():
    pilot = Path("data/ted_pl_v1/pilot_source/772642-2023.xml")
    if not pilot.exists():
        return
    parsed = MODULE.parse_official_xml(pilot.read_bytes())
    assert parsed["authors"]
    assert "Szpital Grochowski" in parsed["authors"][0]
    assert len(parsed["chunks"]) > 10
    assert any("zamówienia" in chunk.casefold() for chunk in parsed["chunks"])
    assert all("@" not in chunk for chunk in parsed["chunks"])


def test_parse_legacy_xml_pilot():
    pilot = Path("data/ted_pl_v1/raw_xml/2024/000427-2024.xml")
    if not pilot.exists():
        return
    parsed = MODULE.parse_official_xml(pilot.read_bytes())
    assert parsed["authors"] == ["Powiat Łobeski – Starostwo Powiatowe w Łobzie"]
    assert any("Przewozy autobusowe" in chunk for chunk in parsed["chunks"])
    assert all("jlewandowski@" not in chunk for chunk in parsed["chunks"])


def test_parse_direct_legacy_form_pilot():
    pilot = Path("data/ted_pl_v1/raw_xml/2024/002404-2024.xml")
    if not pilot.exists():
        return
    parsed = MODULE.parse_official_xml(pilot.read_bytes())
    assert parsed["authors"] == ["Urząd Gminy w Kazimierzu Biskupim"]
    assert any("transportu drogowego" in chunk for chunk in parsed["chunks"])
    assert all("bhoreziak@" not in chunk for chunk in parsed["chunks"])


def test_notice_id():
    assert MODULE.notice_id("https://ted.europa.eu/en/notice/-/detail/2023/772642-2023xml") == "772642-2023"
    assert MODULE.notice_id("https://ted.europa.eu/en/notice/-/detail/2024/35180-2024xml") == "35180-2024"


def test_parse_search_record_keeps_only_polish_narrative():
    record = {
        "buyer-name": {"pol": ["Gmina Testowa"], "eng": ["Test Municipality"]},
        "description-proc": {"pol": "Polski opis zamówienia o długości wystarczającej.", "eng": "English description."},
        "description-lot": {"pol": ["Kontakt: test@example.pl, telefon +48 123 456 789."]},
    }
    parsed = MODULE.parse_search_record(record)
    assert parsed["authors"] == ["Gmina Testowa"]
    assert any("Polski opis" in chunk for chunk in parsed["chunks"])
    assert all("English" not in chunk and "test@example.pl" not in chunk for chunk in parsed["chunks"])
    assert parsed["pii"]["email"] == parsed["pii"]["phone"] == 1
