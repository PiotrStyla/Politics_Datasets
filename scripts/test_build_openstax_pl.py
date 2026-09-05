import ast
import pytest
from build_openstax_pl import extract, license_evidence, page_content, update_registry, normalized_key, near_dedup


def test_extract_keeps_inline_words_and_paragraphs():
    text, _ = extract('<div data-type="page"><h2>Tytul</h2><p>To <b>jest</b> polski tekst.</p><p>Drugi akapit.</p></div>')
    assert text == 'Tytul\n\nTo jest polski tekst.\n\nDrugi akapit.'


def test_content_selector_excludes_navigation_and_fails_closed():
    _, content = page_content('<nav>MENU</nav><div id="main-content"><div data-type="page"><p>Tekst</p></div></div><footer>Footer</footer>')
    assert extract(str(content))[0] == 'Tekst'
    with pytest.raises(ValueError):
        page_content('<html>Access denied</html>')


def test_math_media_and_pii():
    text, _ = extract('<div data-type="page"><figure><p>Picture credit</p><img src="a.png"></figure><p>Wzor: <math><semantics><mi>x</mi><annotation encoding="application/x-tex">x^2</annotation></semantics></math>.</p><p>Kontakt: test@example.com</p></div>')
    assert '$x^2$' in text
    assert 'Picture credit' not in text
    assert 'test@example.com' not in text


def test_nc_license_rejected_and_by_accepted():
    _, content = page_content('<div id="main-content"><div data-type="page">Creative Commons Uznanie autorstwa 4.0 (CC BY 4.0)</div></div>')
    assert license_evidence(content)['license'] == 'CC-BY-4.0'
    content.append(' CC BY-NC-SA 4.0')
    with pytest.raises(ValueError):
        license_evidence(content)


def test_registry_and_dedup():
    original = 'SOURCES = {"wikipedia": {"is_ocr": False}}\n'
    updated = update_registry(original)
    value = ast.literal_eval(ast.parse(updated).body[0].value)
    assert value['wikipedia'] == {'is_ocr': False}
    assert value['openstax_pl']['license'] == 'CC-BY-4.0'
    with pytest.raises(ValueError):
        update_registry(updated)
    assert normalized_key('To  samo\n') == normalized_key('TO SAMO')


def test_mathml_fraction_preserves_structure_without_duplicated_annotation():
    text, changes = extract('<div data-type="page"><math><semantics><mfrac><mi>a</mi><msup><mi>b</mi><mn>2</mn></msup></mfrac><annotation-xml><mi>duplicate</mi></annotation-xml></semantics></math></div>')
    assert '\\frac' in text and '^{2}' in text
    assert 'duplicate' not in text
    assert not changes.get('math_conversion_failed')


def test_near_dedup_retains_different_documents():
    text = ' '.join('word' + str(i) for i in range(100))
    rows = [{'id': 'a', 'text': text}, {'id': 'b', 'text': text + ' added'}, {'id': 'c', 'text': 'completely different text content ' * 20}]
    kept, removed = near_dedup(rows)
    assert [r['id'] for r in kept] == ['a', 'c']
    assert removed[0]['duplicate_of'] == 'a'


def test_empty_math_and_spacing_are_not_missing_operands():
    text, changes = extract('<div data-type="page"><math><semantics><mrow></mrow></semantics></math><math><msup><mn>10</mn><mn>7</mn><mspace width="0.2em"/></msup></math></div>')
    assert '^{7}' in text
    assert changes['empty_math_placeholder_removed'] == 1
    assert changes['math_spacing_removed'] == 1
    assert not changes.get('math_conversion_failed')
    text, changes = extract('<div data-type="page"><math><msup><mi>s</mi></msup></math></div>')
    assert changes['math_conversion_failed'] == 1
    assert '[UNCONVERTED_MATHML]' in text
