from decimal import Decimal as D

from rtech_sync.normalise import check_variant, normalise_text, to_gst_inclusive


def test_normalise_units():
    assert normalise_text("1.5 Sq. mm Wire, 90 Mtr") == "1.5sqmm wire, 90m"
    assert normalise_text("20 Meters") == "20m"


def test_variant_ok_with_unit_spelling_differences():
    r = check_variant("1.5 sq mm; red", "90 m", "Polycab 1.5 sqmm FR Wire - Red - 90 Mtr coil")
    assert r.status == "ok"


def test_decimal_boundary_does_not_false_match():
    r = check_variant("1.5 sq mm", "", "Polycab 11.5 sqmm cable")
    assert r.status == "variant_unconfirmed"
    r = check_variant("1.5 sq mm", "", "Polycab 21.5 sqmm cable")
    assert r.status == "variant_unconfirmed"


def test_word_boundary_for_colours():
    assert check_variant("red", "", "reddish brown wire").status == "variant_unconfirmed"
    assert check_variant("red", "", "Red wire").status == "ok"


def test_missing_hint_token_names_it():
    r = check_variant("1.5 sq mm; blue", "", "Polycab 1.5 sqmm wire red")
    assert r.status == "variant_unconfirmed" and "blue" in r.detail


def test_pack_mismatch_detected_when_page_has_other_pack_of_same_unit():
    r = check_variant("1.5 sq mm", "90 m", "Polycab 1.5 sqmm wire 180 m coil")
    assert r.status == "pack_mismatch" and "180m" in r.detail


def test_pack_not_found_without_other_quantity_is_unconfirmed():
    r = check_variant("1.5 sq mm", "90 m", "Polycab 1.5 sqmm wire")
    assert r.status == "variant_unconfirmed"


def test_pack_90m_not_confirmed_by_190m():
    assert check_variant("", "90 m", "wire 190 m coil").status == "pack_mismatch"


def test_empty_hint_and_pack_cannot_confirm_anything():
    assert check_variant("", "", "anything").status == "variant_unconfirmed"


def test_gst_inclusive_passthrough():
    assert to_gst_inclusive(D(100), "incl_gst", D(18), None) == (D(100), "ok")


def test_gst_exclusive_converted():
    p, s = to_gst_inclusive(D(100), "excl_gst", D(18), None)
    assert (p, s) == (D("118.00"), "ok")


def test_unknown_basis_uses_assumed_else_flags():
    assert to_gst_inclusive(D(100), "unknown", D(18), "incl_gst")[1] == "ok"
    assert to_gst_inclusive(D(100), "unknown", D(18), "excl_gst")[0] == D("118.00")
    assert to_gst_inclusive(D(100), "unknown", D(18), None)[1] == "tax_unknown"


def test_page_basis_beats_assumed():
    assert to_gst_inclusive(D(100), "incl_gst", D(18), "excl_gst")[0] == D(100)


# --- multipack guard (real Moglix title "... (Pack of 5)", 14 Oct 2026)
def test_pack_of_n_page_needs_the_same_n_in_the_row():
    page = "Legrand 6A Mylinc 1 Way Switch, (Pack of 5)"
    assert check_variant("6a; 1 way", "", page).status == "pack_mismatch"
    assert check_variant("6a; 1 way", "1 pc", page).status == "pack_mismatch"
    assert check_variant("6a; 1 way", "pack of 10", page).status == "pack_mismatch"
    assert check_variant("6a; 1 way", "pack of 5", page).status == "ok"
    assert check_variant("6a; 1 way", "5 pcs", page).status == "ok"


def test_pack_of_one_is_not_a_multipack():
    assert check_variant("red", "", "Wire Pack of 1 Red").status == "ok"


def test_page_with_two_different_pack_counts_is_refused():
    page = "Switch (Pack of 5) also sold as box of 20"
    assert check_variant("switch", "pack of 5", page).status == "pack_mismatch"


def test_line_name_plus_matches_across_spellings():
    # real: IndustryBuying/HomeRun "Optima+", Moglix slug "optima-plus" (15 Oct 2026)
    assert check_variant("optima+; 1.5 sq mm; red", "90 m", "Polycab Optima Plus 1.5 sqmm red 90m").status == "ok"
    assert check_variant("optima+; 1.5 sq mm; red", "90 m", "Polycab Optima+ 1.5 Sq.mm Red (90 m)").status == "ok"
    assert check_variant("optima+; 1.5 sq mm", "90 m", "Polycab Optima 1.5 sqmm 90m").status == "variant_unconfirmed"
