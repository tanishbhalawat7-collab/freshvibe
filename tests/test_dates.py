from datetime import date

from app.dates import extract

T = date(2026, 11, 26)


def run(*lines):
    return extract([(l, 0.92) for l in lines], today=T)


def test_mfg_and_expiry_are_distinguished():
    r = run("MFD: 03/2025", "EXP: 02/2027")
    assert r["mfg"]["value"] == "2025-03" and r["expiry"]["value"] == "2027-02"


def test_month_precision_preserved():
    r = run("BEST BEFORE: SEP 2026")
    assert r["expiry"]["value"] == "2026-09" and r["expiry"]["precision"] == "month"


def test_day_month_year_and_iso_and_named():
    assert run("EXP 15-08-2027")["expiry"]["value"] == "2027-08-15"
    assert run("USE BY 2027-06-30")["expiry"]["value"] == "2027-06-30"
    assert run("Best before 12 Jan 2028")["expiry"]["value"] == "2028-01-12"
    assert run("EXP 05-2027")["expiry"]["value"] == "2027-05"


def test_unlabelled_dates_never_become_expiry():
    r = run("12/03/2026", "15/08/2027")
    assert r["expiry"] is None and len(r["all_dates"]) == 2 and r["issues"]


def test_invalid_calendar_date_rejected():
    r = run("EXP 30/02/2027")
    assert r["expiry"] is None and r["rejected"]


def test_packed_is_not_expiry():
    r = run("PKD 14 MAR 2026")
    assert r["expiry"] is None and r["packed"]["value"] == "2026-03-14"


def test_label_on_previous_line_and_paired_labels():
    assert run("EXPIRY DATE", "2027-06-30")["expiry"]["value"] == "2027-06-30"
    r = run("MFG/EXP: 01/25 12/26")
    assert r["mfg"]["value"] == "2025-01" and r["expiry"]["value"] == "2026-12"


def test_shelf_life_derived_only_from_real_base():
    r = run("Mfd: 05/2026", "Best before 18 months from manufacture")
    assert r["expiry"]["value"] == "2027-10" and r["expiry"]["derived"]
    assert run("Best before 18 months from manufacture")["expiry"] is None


def test_ocr_confusions_fixed_with_lower_confidence():
    r = run("EXP:I5/O8/2O27")
    assert r["expiry"]["value"] == "2027-08-15" and r["expiry"]["confidence"] < 0.92


def test_expiry_before_mfg_flagged():
    r = run("MFG 10/10/2027", "EXP 10/10/2026")
    assert r["expiry"]["confidence"] < 0.6 and r["issues"]


def test_original_text_preserved_and_batch():
    r = run("Batch No: AB1234  EXP 31/12/2027")
    assert r["expiry"]["raw"] == "31/12/2027" and r["batch"]["value"] == "AB1234"
