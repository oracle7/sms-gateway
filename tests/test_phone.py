from services.phone import format_phone_display, normalize_contact_phone


def test_us_ten_and_eleven_digits():
    assert normalize_contact_phone("9295551234") == "+19295551234"
    assert normalize_contact_phone("(929) 555-1234") == "+19295551234"
    assert normalize_contact_phone("1-929-555-1234") == "+19295551234"
    assert normalize_contact_phone("+19295551234") == "+19295551234"


def test_shortcodes_and_legacy_plus_shortcode():
    assert normalize_contact_phone("22660") == "22660"
    assert normalize_contact_phone("+22660") == "22660"
    assert normalize_contact_phone("72833") == "72833"


def test_international_numbers():
    assert normalize_contact_phone("+442079460958") == "+442079460958"
    assert normalize_contact_phone("011442079460958") == "+442079460958"


def test_unknown_and_alphanumeric():
    assert normalize_contact_phone(None) == "unknown"
    assert normalize_contact_phone("") == "unknown"
    assert normalize_contact_phone("unknown") == "unknown"
    assert normalize_contact_phone("UNKNOWN") == "unknown"
    assert normalize_contact_phone("ClinicAlert") == "ClinicAlert"


def test_display_formatting():
    assert format_phone_display("+19295551234") == "(929) 555-1234"
    assert format_phone_display("22660") == "22660"
    assert format_phone_display("unknown") == "Unknown Sender"
