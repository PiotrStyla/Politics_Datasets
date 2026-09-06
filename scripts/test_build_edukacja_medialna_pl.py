from pathlib import Path
import importlib.util

SCRIPT = Path(__file__).with_name("build_edukacja_medialna_pl.py")
spec = importlib.util.spec_from_file_location("builder", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_listing_only_accepts_lesson_slugs():
    html = '<a href="/lekcje/test/">yes</a><a href="/lekcje/">no</a><a href="https://evil.example/lekcje/x/">no</a>'
    assert builder.lesson_links(html) == ["https://edukacjamedialna.edu.pl/lekcje/test/"]


def test_parse_xml_extracts_authors_rights_and_omits_reading_list():
    xml = b'''<utwor xmlns:dc="http://purl.org/dc/elements/1.1/"><rdf><dc:title>Tytul</dc:title><dc:identifier.url>https://edukacjamedialna.edu.pl/lekcje/x/</dc:identifier.url><dc:creator.textbook>Kowalska, Anna</dc:creator.textbook><dc:date>2012-01-02</dc:date><dc:rights>CC BY-SA 3.0</dc:rights><dc:rights.license>https://creativecommons.org/licenses/by-sa/3.0/</dc:rights.license></rdf><powiesc><naglowek_rozdzial>Wiedza</naglowek_rozdzial><akap>To jest wystarczajaco dlugi tekst lekcji.</akap><naglowek_rozdzial>Czytelnia</naglowek_rozdzial><akap>Zewnetrzna bibliografia</akap></powiesc></utwor>'''
    row = builder.parse_xml(xml, "https://edukacjamedialna.edu.pl/lekcje/x/")
    assert row["title"] == "Tytul"
    assert row["creators"] == ["Kowalska, Anna"]
    assert row["created"] == "2012-01-02"
    assert "Wiedza" in row["text"] and "Zewnetrzna bibliografia" not in row["text"]


def test_normalize_is_deterministic():
    assert builder.normalize(" A\u00a0 B\n\n\n C ") == "A B\n\nC"
