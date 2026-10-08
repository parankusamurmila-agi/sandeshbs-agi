from app.services import doc_converter


def test_is_docx_true_for_docx_extension():
    assert doc_converter.is_docx("Deficiency_Letter.docx") is True
    assert doc_converter.is_docx("Deficiency_Letter.DOCX") is True


def test_is_docx_false_for_other_extensions():
    assert doc_converter.is_docx("Deficiency_Letter.pdf") is False
    assert doc_converter.is_docx("Deficiency_Letter") is False
