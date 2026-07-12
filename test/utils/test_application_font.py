import hashlib

from app.utils.application_font import (
    EXPECTED_FAMILY,
    FONT_SHA256,
    bundled_font_path,
    install_application_font,
)


def test_bundled_cjk_font_is_installed_as_application_font(qapp):
    data = bundled_font_path().read_bytes()
    assert len(data) == 16437364
    assert hashlib.sha256(data).hexdigest() == FONT_SHA256
    assert install_application_font(qapp) == EXPECTED_FAMILY
    assert qapp.font().family() == EXPECTED_FAMILY
