from pathlib import Path

from app.parser import parse_ct200_pdf


PDF = Path("data/ct200_manual.pdf")


def nodes():
    return parse_ct200_pdf(PDF).flatten()


def test_duplicate_error_codes_have_distinct_identity_and_parents():
    errors = [node for node in nodes() if node.heading == "Error Codes"]
    assert len(errors) == 2
    assert errors[0].uid != errors[1].uid
    assert [node.parent_uid for node in errors] == ["parsed-13", "parsed-23"]


def test_skipped_numbering_level_attaches_to_closest_real_ancestor():
    battery = next(node for node in nodes() if node.number == "2.1.1.1")
    assert battery.nominal_level == 4
    assert battery.depth == 3
    assert battery.numbering_gap is True
    assert battery.parent_uid == "parsed-5"  # 2.1; no invented 2.1.1 node


def test_out_of_order_siblings_remain_siblings_under_section_three():
    parsed = parse_ct200_pdf(PDF)
    operation = next(node for node in parsed.flatten() if node.number == "3")
    assert [child.number for child in operation.children] == ["3.1", "3.2", "3.4", "3.3"]


def test_cross_page_text_stays_with_the_open_section():
    powering_on = next(node for node in nodes() if node.number == "3.1")
    assert "Use the profile button to select User 1 or User 2" in powering_on.body_text


def test_genuine_specification_grid_is_preserved_as_a_table_block():
    specifications = next(node for node in nodes() if node.number == "2.1")
    table = next(block for block in specifications.blocks if block.block_type == "table")
    assert table.cells and table.cells[0] == ["Parameter", "Value"]
