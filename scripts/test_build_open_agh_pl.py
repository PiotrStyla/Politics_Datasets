import ast
import io
import zipfile
import pytest
from build_open_agh_pl import extract, walk, module_map, license_from_epub, near_dedup, registry, SOURCE


def test_wrapping_inline_words_and_paragraphs():
    text, _ = extract('Pierwsza\nlinia.<p>To <b>jest</b>\n tekst.</p><p>Drugi.</p>')
    assert text == 'Pierwsza linia.\n\nTo jest tekst.\n\nDrugi.'


def test_math_media_table_and_pii():
    text, counts = extract(r'<figure><img src="x"><figcaption>Remove</figcaption></figure><p>Woda: <span>\(\ce{H_2O}\)</span> H<sub>2</sub>O.</p><table><tr><td>A</td><td>B</td></tr></table><p>a@example.com</p>')
    assert r'\(\ce{H_2O}\)' in text and 'H_{2}O' in text
    assert 'A | B |' in text
    assert 'Remove' not in text and 'example.com' not in text
    assert counts['email'] == 1 and counts['unbalanced_math_delimiters'] == 0


def test_fail_closed_and_math_delimiters():
    with pytest.raises(ValueError):
        extract('<html><body>Login</body></html>')
    assert extract(r'<p>Broken \(x</p>')[1]['unbalanced_math_delimiters'] == 1


def test_nested_inventory_and_conflicting_revisions():
    module = {'module_id': 5, 'title': 'One', 'revision': 1, 'authors': ['Author']}
    assert module_map([{'occurrences': [module]}, {'occurrences': [module]}]) == {5: module}
    with pytest.raises(ValueError):
        module_map([{'occurrences': [module]}, {'occurrences': [{**module, 'revision': 2}]}])
    assert list(walk([{'title': 'Chapter', 'children': [{'_embedded': {'module': {'id': 5}}}]}])) == [({'id': 5}, 'Chapter')]


def test_book_specific_license():
    def epub(license_path):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z:
            z.writestr('OEBPS/main.xhtml', f'<html><body>Na tych samych warunkach /handbook/29<a href="https://creativecommons.org/licenses/{license_path}/4.0">license</a></body></html>')
        return buffer.getvalue()
    assert license_from_epub(epub('by-sa'), 29)['license'] == 'CC-BY-SA-4.0'
    with pytest.raises(ValueError):
        license_from_epub(epub('by-nc-sa'), 29)
    with pytest.raises(ValueError):
        license_from_epub(epub('by-sa'), 37)


def test_registry_and_near_duplicate():
    base = 'SOURCES = {"existing": {"is_ocr": False}}\n'
    result = ast.literal_eval(ast.parse(registry(base)).body[0].value)
    assert result['existing'] == {'is_ocr': False} and result[SOURCE]['license'] == 'CC-BY-SA-4.0'
    words = ' '.join('word' + str(n) for n in range(100))
    kept, dropped = near_dedup([{'id': 'a', 'text': words}, {'id': 'b', 'text': words + ' extra'}])
    assert len(kept) == 1 and dropped[0]['duplicate_of'] == 'a'
