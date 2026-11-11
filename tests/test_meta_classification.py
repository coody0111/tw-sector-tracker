"""族群分類規則（config.META_PRIORITY_LIST / META_SECTORS）——2026-11-11 Cody 要求修正的案例。

子族群標籤組合取自 MoneyDJ 實際資料（data/sectors/industry_sectors.csv）。
"""
from config import META_PRIORITY_LIST, get_meta_by_priority, get_meta_sector


def test_foundry_needs_foundry_tag():
    assert get_meta_by_priority(["晶圓代工", "IC製造"]) == "晶圓代工"


def test_memory_maker_with_ic_manufacturing_tag_is_memory():
    # 立萬利、方土昶這類：IC製造＋DRAM，以前被 IC製造 拉進晶圓代工
    assert get_meta_by_priority(["IC製造", "DRAM", "非揮發性記憶體"]) == "記憶體"


def test_compound_semiconductor_separate_from_foundry():
    assert get_meta_by_priority(["砷化鎵相關", "化合物晶圓"]) == "化合物半導體"


def test_third_gen_semiconductor_is_compound():
    # 嘉晶：第三類半導體＋磊晶，Cody 2026-11-11 決定歸化合物半導體
    assert get_meta_by_priority(["第三類半導體", "磊晶"]) == "化合物半導體"
    assert get_meta_by_priority(["第三類半導體"]) == "化合物半導體"


def test_probe_card_is_test_interface_not_packaging():
    assert get_meta_by_priority(["探針、探針卡", "IC測試"]) == "測試介面"


def test_test_board_is_test_interface_not_substrate():
    # 精測、雍智：測試用板卡，以前排在載板
    assert get_meta_by_priority(["測試用板卡", "IC基板"]) == "測試介面"


def test_packaging_equipment_is_equipment():
    assert get_meta_by_priority(["封測用設備"]) == "半導體設備"


def test_wafer_and_epi_are_materials():
    assert get_meta_by_priority(["矽晶圓"]) == "半導體材料"
    assert get_meta_by_priority(["磊晶"]) == "半導體材料"


def test_optical_epi_goes_to_optical_comm():
    assert get_meta_by_priority(["光通訊元件磊晶"]) == "光通訊"
    assert get_meta_sector("光通訊元件磊晶") == "光通訊"


def test_ic_packaging_still_matches_packaging_tags():
    assert get_meta_by_priority(["IC封裝測試"]) == "IC封裝"


def test_new_sub_sector_moves_in_meta_sectors():
    assert get_meta_sector("探針、探針卡") == "測試介面"
    assert get_meta_sector("測試用板卡") == "測試介面"
    assert get_meta_sector("封測用設備") == "半導體設備"
    assert get_meta_sector("化合物晶圓") == "化合物半導體"
    assert get_meta_sector("矽晶圓") == "半導體材料"


def test_priority_list_meta_names_unique():
    names = [m for m, _ in META_PRIORITY_LIST]
    assert len(names) == len(set(names))
