# -*- coding: utf-8 -*-
"""
飞书多维表格记账模块（雨云签到记录）。

表结构（行=日期，列=账号，交叉格=当天积分）：
    编号(文本,主键) | 日期(文本 YYYY-MM-DD) | <账号1>(数字) | <账号2>(数字) | ...

写入逻辑：按"日期"定位当天行（文本精确匹配），存在则更新该账号单元格，
不存在则新建一行。同一天重复运行是幂等的（覆盖，不产生重复行）。
日期使用纯文本字段，规避飞书日期字段的时区显示问题。

凭据从环境变量读取（rainyun.py 启动时会把 config.py 的值注入环境变量）：
    LARK_APP_ID / LARK_APP_SECRET / LARK_APP_TOKEN / LARK_TABLE_ID
"""
import os
import requests
from datetime import datetime

APP_ID = os.getenv("LARK_APP_ID")
APP_SECRET = os.getenv("LARK_APP_SECRET")
APP_TOKEN = os.getenv("LARK_APP_TOKEN")
TABLE_ID = os.getenv("LARK_TABLE_ID")

_TOKEN_CACHE = {"t": None}


def enabled() -> bool:
    """飞书记账是否可用（凭据齐全才启用）。"""
    return bool(APP_TOKEN and TABLE_ID and APP_ID and APP_SECRET)


def get_token() -> str:
    if _TOKEN_CACHE["t"]:
        return _TOKEN_CACHE["t"]
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=20,
    )
    t = r.json().get("tenant_access_token")
    _TOKEN_CACHE["t"] = t
    return t


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }


def _list_fields() -> dict:
    r = requests.get(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields",
        headers=_headers(),
        timeout=20,
    )
    return {f["field_name"]: f for f in r.json().get("data", {}).get("items", [])}


def ensure_column(account: str) -> None:
    """确保该账号对应的数字列已存在，不存在则创建。"""
    fields = _list_fields()
    if account in fields:
        return
    r = requests.post(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields",
        headers=_headers(),
        json={"field_name": account, "field_type": 2, "property": {"formatter": "0"}},
        timeout=20,
    )
    if r.status_code not in (200, 201):
        # 并发建列可能冲突，忽略；下次写入会重试
        pass


def today_str() -> str:
    # 文本字段，按服务器本地日期写入（服务器时区请设为 Asia/Shanghai）
    return datetime.now().strftime("%Y-%m-%d")


def _find_row_by_date(date_str: str):
    body = {
        "filter": {
            "conjunction": "and",
            "conditions": [
                {"field_name": "日期", "operator": "is", "value": date_str}
            ],
        }
    }
    r = requests.post(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/search",
        headers=_headers(),
        json=body,
        timeout=20,
    )
    items = r.json().get("data", {}).get("items", [])
    if items:
        return items[0]["record_id"], items[0].get("fields", {})
    return None, None


def _next_seq() -> int:
    r = requests.get(
        f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records?page_size=100",
        headers=_headers(),
        timeout=20,
    )
    items = r.json().get("data", {}).get("items", [])
    maxn = 0
    for it in items:
        try:
            maxn = max(maxn, int(it["fields"].get("编号", 0)))
        except Exception:
            pass
    return maxn + 1


def upsert(account: str, points: int) -> None:
    """
    把某账号当天的积分写入飞书表。
    - points > 0 才写入数字（避免失败重跑时用 0 覆盖已有的有效积分）。
    - 按日期定位行：存在则更新该列，不存在则新建一行。
    """
    if not enabled():
        return
    ensure_column(account)
    date_str = today_str()
    rid, _ = _find_row_by_date(date_str)

    payload = {}
    if points and points > 0:
        payload[account] = points

    if rid:
        r = requests.put(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{rid}",
            headers=_headers(),
            json={"fields": payload},
            timeout=20,
        )
    else:
        payload["编号"] = str(_next_seq())
        payload["日期"] = date_str
        r = requests.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
            headers=_headers(),
            json={"fields": payload},
            timeout=20,
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"飞书写入失败: {r.status_code} {r.text[:200]}")
