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
        json={"field_name": account, "type": 2, "property": {"formatter": "0"}},
        timeout=20,
    )
    if r.status_code not in (200, 201) or r.json().get("code") not in (0, None):
        # 并发建列可能冲突，忽略；下次写入会重试
        pass


def today_str() -> str:
    # 文本字段，按服务器本地日期写入（服务器时区请设为 Asia/Shanghai）
    return datetime.now().strftime("%Y-%m-%d")


_ROW_CACHE = {}  # date_str -> record_id（同进程内缓存，避免重复拉取）


def _list_all_records() -> list:
    """分页拉取全部记录（不依赖服务端过滤，规避文本字段过滤值格式坑）。"""
    items = []
    page_token = None
    while True:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        r = requests.get(url, headers=_headers(), timeout=20).json()
        data = r.get("data", {})
        items.extend(data.get("items", []))
        page_token = data.get("page_token")
        if not page_token or not data.get("items"):
            break
    return items


def _find_row_by_date(date_str: str):
    """按日期(文本)在本地匹配当天行。命中返回 (record_id, fields)，否则 (None, None)。"""
    if date_str in _ROW_CACHE and _ROW_CACHE[date_str]:
        return _ROW_CACHE[date_str], None
    for it in _list_all_records():
        if it.get("fields", {}).get("日期") == date_str:
            _ROW_CACHE[date_str] = it["record_id"]
            return it["record_id"], it.get("fields", {})
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


def _write_record(rid, payload, date_str):
    """写入一行：rid 给定则更新，否则新建。返回 (是否成功, 响应体)。"""
    if rid:
        r = requests.put(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{rid}",
            headers=_headers(),
            json={"fields": payload},
            timeout=20,
        )
    else:
        p = dict(payload)
        p["编号"] = str(_next_seq())
        p["日期"] = date_str
        r = requests.post(
            f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records",
            headers=_headers(),
            json={"fields": p},
            timeout=20,
        )
        _data = r.json().get("data", {})
        _new_rid = _data.get("record_id") or _data.get("record", {}).get("record_id")
        if r.status_code in (200, 201) and _new_rid:
            _ROW_CACHE[date_str] = _new_rid
    _body = r.json()
    ok = r.status_code in (200, 201) and _body.get("code") in (0, None)
    return ok, _body


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

    ok, body = _write_record(rid, payload, date_str)
    # 新账号列刚创建可能未即时就绪（FieldNameNotFound），重建列后重试一次
    if not ok and body.get("code") == 1254045:
        ensure_column(account)
        rid, _ = _find_row_by_date(date_str)
        ok, body = _write_record(rid, payload, date_str)
    if not ok:
        raise RuntimeError(f"飞书写入失败: code={body.get('code')} {body}")
