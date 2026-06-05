INCLUDE_SECTOR_CODES = {
    # ── 電子/半導體（全部 383 個族群）──
    "C023",

    # ── 機器人 / 自動化 ──
    "C015160",  # 自動化設備
    "C015180",  # 機器人
    "C015181",  # 人形機器人
    "C015182",  # 協作機器人
    "C015183",  # 機器手臂

    # ── 電池材料 ──
    "C017490",  # 電池材料相關
    "C017495",  # 正極材料
    "C017496",  # 負極材料
    "C017497",  # 電解液
    "C017498",  # 電池隔離膜

    # ── 車用電子 ──
    "C022006",  # 電動車
    "C022007",  # 電動機車
    "C022052",  # 車用電子
    "C022080",  # 車用鋰電池
    "C022088",  # LIDAR

    # ── 光纖光纜 ──
    "C016015",  # 光纖光纜

    # ── 無人機 ──
    "C099346",  # 無人機
    "C099347",  # 商用無人機
    "C099348",  # 軍用無人機
}


def should_include_sector(sector_code: str) -> bool:
    """Return True if this sector should be tracked."""
    for prefix_or_code in INCLUDE_SECTOR_CODES:
        if sector_code == prefix_or_code or sector_code.startswith(prefix_or_code):
            return True
    return False
