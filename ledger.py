# -*- coding: utf-8 -*-
"""
飞书多维表格记账模块（雨云签到记录）。

表结构（行=日期，列=账号，交叉格=当天积分）：
    编号(文本,主键) | 日期(文本 YYYY-MM-DD) | <账号1>(数字) | <账号2>(数字) | ...

功能：
- 自动建表：凭据配置齐全后，首次运行自动校验表结构，表不存在则自动创建
  （新 table_id 会尽力回写本地 config.py，GitHub Actions 下请手动同步 Secrets）
- 自动修复：编号/日期字段缺失自动创建；类型不符（如日期被建成日期类型）自动删除重建；
  账号列自动创建且强制数字类型
- 自动重试：网络异常 / 限流(429) / token 失效自动重试刷新；字段未就绪(1254045)重建后重试
- 自检 CLI：python ledger.py check（只读）/ fix（自动修复）/ test（修复+写测试行验证+删除）

写入逻辑：按"日期"定位当天行（文本精确匹配），存在则更新该账号单元格，
不存在则新建一行。同一天重复运行是幂等的（覆盖，不产生重复行）。
日期使用纯文本字段，规避飞书日期字段的时区显示问题。

凭据从环境变量读取（rainyun.py 启动时会把 config.py 的值注入环境变量）：
    LARK_APP_ID / LARK_APP_SECRET / LARK_APP_TOKEN / LARK_TABLE_ID
"""
import os
import sys
import re
import time
import requests
from datetime import datetime

APP_ID = os.getenv("LARK_APP_ID")
APP_SECRET = os.getenv("LARK_APP_SECRET")
APP_TOKEN = os.getenv("LARK_APP_TOKEN")
TABLE_ID = os.getenv("LARK_TABLE_ID")

_TOKEN_CACHE = {"t": None}
_SCHEMA_OK = False  # 进程内表结构已校验标志（避免每次写入都拉取字段）

# 飞书多维表格字段类型：1=文本 2=数字
_TYPE_TEXT = 1
_TYPE_NUMBER = 2
DEFAULT_TABLE_NAME = "雨云签到记录"
_TEST_DATE = "2099-12-31"  # 自检测试行日期（未来日期，不与真实数据冲突）


def enabled() -> bool:
    """飞书记账是否可用（凭据齐全才启用）。"""
    return bool(APP_TOKEN and TABLE_ID and APP_ID and APP_SECRET)


def _get_token(refresh=False) -> str:
    if refresh:
        _TOKEN_CACHE["t"] = None
    if _TOKEN_CACHE["t"]:
        return _TOKEN_CACHE["t"]
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
        timeout=20,
    )
    _TOKEN_CACHE["t"] = r.json().get("tenant_access_token")
    return _TOKEN_CACHE["t"]


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    return f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}"


def _api(method, url, payload=None, retries=2):
    """带重试的统一 API 调用。返回 (r, body)。
    重试场景：网络异常、限流(429)、token 失效（401 或 99991661~99991670）。
    业务错误（如字段不存在 1254045）不重试，直接返回给上层处理。
    """
    last = None
    for attempt in range(retries + 1):
        try:
            r = requests.request(method, url, headers=_headers(),
                                 json=payload, timeout=25)
            body = r.json()
            code = body.get("code")
            if r.status_code in (200, 201) and code in (0, None):
                return r, body
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1))
                last = body
                continue
            if r.status_code == 401 or (isinstance(code, int) and 99991660 <= code <= 99991670):
                _get_token(refresh=True)
                last = body
                continue
            return r, body
        except requests.RequestException as e:
            last = {"_net_error": str(e)}
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
    return None, last


# ---------- 表与字段 ----------

def get_table_info() -> dict:
    """表信息；表不存在返回 None。
    用列表接口判断（部分 Base 的单表查询路由返回 404，列表接口已验证可用）。
    """
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables"
    r, body = _api("GET", url)
    if r is None or body.get("code") not in (0, None):
        return None
    for t in body.get("data", {}).get("items", []):
        if t.get("table_id") == TABLE_ID:
            return t
    return None


def create_table() -> str:
    """在 Base(app) 下自动创建数据表，返回新 table_id。"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables"
    payload = {
        "table": {
            "name": DEFAULT_TABLE_NAME,
            "default_view_name": "表格",
            "fields": [
                {"field_name": "编号", "type": _TYPE_TEXT},
                {"field_name": "日期", "type": _TYPE_TEXT},
            ],
        }
    }
    r, body = _api("POST", url, payload)
    if r is None or body.get("code") not in (0, None):
        raise RuntimeError(f"自动建表失败: {body}")
    return body["data"]["table_id"]


def _write_back_table_id(new_table_id: str) -> None:
    """尽力把新 table_id 回写本地 config.py（若存在）；否则打印提示。"""
    global TABLE_ID
    TABLE_ID = new_table_id
    if os.path.exists("config.py"):
        try:
            src = open("config.py", encoding="utf-8").read()
            if "LARK_TABLE_ID" in src:
                src2 = re.sub(r'(LARK_TABLE_ID\s*=\s*)[\'"][^\'"]*[\'"]',
                              r'\g<1>"%s"' % new_table_id, src, count=1)
                open("config.py", "w", encoding="utf-8").write(src2)
                print(f"✓ 已自动更新 config.py 的 LARK_TABLE_ID = {new_table_id}")
                return
        except Exception as e:
            print(f"⚠ 自动回写失败: {e}")
    print(f"提示: 请在 config.py / GitHub Secrets 中设置 LARK_TABLE_ID = {new_table_id}")


def list_fields() -> dict:
    """全量拉取字段，返回 {field_name: field}。"""
    r, body = _api("GET", f"{_base_url()}/fields")
    if r is None or body.get("code") not in (0, None):
        raise RuntimeError(f"拉取字段失败: {body}")
    return {f["field_name"]: f for f in body.get("data", {}).get("items", [])}


def create_field(name: str, ftype: int, formatter: str = None) -> None:
    payload = {"field_name": name, "type": ftype}
    if formatter:
        payload["property"] = {"formatter": formatter}
    r, body = _api("POST", f"{_base_url()}/fields", payload)
    if r is None or body.get("code") not in (0, None):
        raise RuntimeError(f"创建字段「{name}」失败: {body}")


def delete_field(field_id: str) -> None:
    r, body = _api("DELETE", f"{_base_url()}/fields/{field_id}")
    if r is None or body.get("code") not in (0, None):
        raise RuntimeError(f"删除字段失败: {body}")


def ensure_schema() -> dict:
    """自动建表 + 校验/修复基础字段（编号/日期=文本）。返回状态报告。"""
    global _SCHEMA_OK
    report = {"table": "ok", "fields": {}, "actions": []}
    if not enabled():
        report["table"] = "disabled"
        return report

    # 1) 表不存在 → 自动创建
    info = get_table_info()
    if info is None:
        new_id = create_table()
        report["actions"].append(f"自动创建数据表「{DEFAULT_TABLE_NAME}」（id={new_id}）")
        _write_back_table_id(new_id)

    # 2) 基础字段：缺失创建 / 类型不符删除重建
    fields = list_fields()
    for name, ftype in (("编号", _TYPE_TEXT), ("日期", _TYPE_TEXT)):
        f = fields.get(name)
        if f is None:
            create_field(name, ftype)
            report["fields"][name] = "created"
            report["actions"].append(f"创建字段「{name}」(文本)")
        elif f.get("type") != ftype:
            delete_field(f["field_id"])
            create_field(name, ftype)
            report["fields"][name] = "recreated"
            report["actions"].append(f"字段「{name}」类型不符，已删除重建为文本")
        else:
            report["fields"][name] = "ok"
    _SCHEMA_OK = True
    return report


def ensure_column(account: str) -> None:
    """确保账号列为数字类型：缺失创建 / 类型不符删除重建。"""
    try:
        fields = list_fields()
    except Exception:
        return
    f = fields.get(account)
    if f is None:
        create_field(account, _TYPE_NUMBER, formatter="0")
    elif f.get("type") != _TYPE_NUMBER:
        delete_field(f["field_id"])
        create_field(account, _TYPE_NUMBER, formatter="0")


# ---------- 记录读写 ----------

def today_str() -> str:
    # 文本字段，按服务器本地日期写入（服务器时区请设为 Asia/Shanghai）
    return datetime.now().strftime("%Y-%m-%d")


_ROW_CACHE = {}  # date_str -> record_id（同进程内缓存，避免重复拉取）


def _list_all_records() -> list:
    """分页拉取全部记录（不依赖服务端过滤，规避文本字段过滤值格式坑）。"""
    items = []
    page_token = None
    while True:
        url = f"{_base_url()}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        r, body = _api("GET", url)
        if r is None:
            break
        data = body.get("data", {})
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
    r, body = _api("GET", f"{_base_url()}/records?page_size=100")
    if r is None:
        return 1
    maxn = 0
    for it in body.get("data", {}).get("items", []):
        try:
            maxn = max(maxn, int(it["fields"].get("编号", 0)))
        except Exception:
            pass
    return maxn + 1


def _write_record(rid, payload, date_str):
    """写入一行：rid 给定则更新，否则新建。返回 (是否成功, 响应体)。"""
    if rid:
        r, body = _api("PUT", f"{_base_url()}/records/{rid}", {"fields": payload})
    else:
        p = dict(payload)
        p["编号"] = str(_next_seq())
        p["日期"] = date_str
        r, body = _api("POST", f"{_base_url()}/records", {"fields": p})
        if r is not None and body.get("code") in (0, None):
            data = body.get("data", {})
            new_rid = data.get("record_id") or data.get("record", {}).get("record_id")
            if new_rid:
                _ROW_CACHE[date_str] = new_rid
    ok = r is not None and r.status_code in (200, 201) and body.get("code") in (0, None)
    return ok, body


def upsert(account: str, points: int) -> None:
    """
    把某账号当天的积分写入飞书表。
    - 首次调用自动完成建表/建字段/修复（ensure_schema）。
    - points > 0 才写入数字（避免失败重跑时用 0 覆盖已有的有效积分）。
    - 按日期定位行：存在则更新该列，不存在则新建一行。
    - 字段未就绪(1254045)自动重建账号列并重试一次。
    """
    if not enabled():
        return
    if not _SCHEMA_OK:
        ensure_schema()
    ensure_column(account)
    date_str = today_str()
    rid, _ = _find_row_by_date(date_str)

    payload = {}
    if points and points > 0:
        payload[account] = points

    ok, body = _write_record(rid, payload, date_str)
    if not ok and body and body.get("code") == 1254045:
        # 新账号列刚创建可能未即时就绪（FieldNameNotFound），重建列后重试一次
        ensure_column(account)
        rid, _ = _find_row_by_date(date_str)
        ok, body = _write_record(rid, payload, date_str)
    if not ok:
        raise RuntimeError(f"飞书写入失败: code={body.get('code') if body else body}")


# ---------- 自检 CLI ----------

def _mask(s):
    return f"{s[:6]}***" if s else "(空)"


def cmd_check() -> int:
    """只读检查表结构。"""
    print("=== 飞书表格结构检查 ===")
    print(f"APP_ID={_mask(APP_ID)} APP_TOKEN={_mask(APP_TOKEN)} TABLE_ID={_mask(TABLE_ID)}")
    if not enabled():
        print("凭据不齐全：需要 LARK_APP_ID / LARK_APP_SECRET / LARK_APP_TOKEN / LARK_TABLE_ID 四项")
        return 1
    info = get_table_info()
    if info is None:
        print("✗ 数据表不存在（TABLE_ID 无效）→ 运行 `python ledger.py fix` 可自动建表")
        return 1
    print(f"表: 「{info.get('name')}」 (id={info.get('table_id')})")
    fields = list_fields()
    bad = 0
    for name in ("编号", "日期"):
        f = fields.get(name)
        if f is None:
            print(f"  ✗ 字段「{name}」缺失")
            bad += 1
        elif f.get("type") == _TYPE_TEXT:
            print(f"  ✓ 字段「{name}」(文本)")
        else:
            print(f"  ✗ 字段「{name}」类型不符(实际 type={f.get('type')}，应为文本)")
            bad += 1
    accts = [n for n in fields if n not in ("编号", "日期")]
    print(f"账号列 {len(accts)} 个（自动维护）: {', '.join(accts[:8]) or '无'}{'...' if len(accts) > 8 else ''}")
    print("✓ 结构正常，可直接签到" if bad == 0 else f"✗ 发现 {bad} 处问题 → 运行 `python ledger.py fix` 修复")
    return 0 if bad == 0 else 1


def cmd_fix() -> int:
    """自动修复表结构（建表/建字段/重建类型错误字段）。"""
    print("=== 飞书表格结构修复 ===")
    report = ensure_schema()
    if report["table"] == "disabled":
        print("凭据不齐全：需要 LARK_APP_ID / LARK_APP_SECRET / LARK_APP_TOKEN / LARK_TABLE_ID 四项")
        return 1
    if not report["actions"]:
        print("✓ 表结构已就绪，无需修复")
    for a in report["actions"]:
        print("  ", a)
    print("✓ 修复完成")
    return 0


def cmd_test() -> int:
    """修复表结构 + 写入一行测试记录验证链路，验证后删除。"""
    print("=== 飞书表格自检（修复 + 写入链路验证）===")
    report = ensure_schema()
    if report["table"] == "disabled":
        print("凭据不齐全：需要 LARK_APP_ID / LARK_APP_SECRET / LARK_APP_TOKEN / LARK_TABLE_ID 四项")
        return 1
    for a in report["actions"]:
        print("  ", a)
    if not report["actions"]:
        print("  ✓ 表结构已就绪")

    print("  写入测试行（日期=2099-12-31，验证后删除）...")
    ok, body = _write_record(None, {"编号": "T", "日期": _TEST_DATE}, _TEST_DATE)
    if not ok:
        print(f"  ✗ 写入失败: {body}")
        return 1
    data = body.get("data", {})
    rid = data.get("record_id") or data.get("record", {}).get("record_id")
    print(f"  ✓ 写入成功 record_id={rid}")
    r2, b2 = _api("GET", f"{_base_url()}/records/{rid}")
    if r2 is not None and b2.get("code") in (0, None):
        rec = b2.get("data", {}).get("record", {})
        fld = rec.get("fields", {})
        print(f"  ✓ 读回验证: 日期={fld.get('日期')} 编号={fld.get('编号')}")
    r3, b3 = _api("DELETE", f"{_base_url()}/records/{rid}")
    if r3 is not None and b3.get("code") in (0, None):
        print("  ✓ 测试行已删除，表保持干净")
    else:
        print(f"  ⚠ 测试行删除失败（可手动删除 record_id={rid}）: {b3}")
    print("✓ 自检通过：表结构 + 写入链路均正常")
    return 0


if __name__ == "__main__":
    sub = sys.argv[1] if len(sys.argv) > 1 else "test"
    if sub == "check":
        sys.exit(cmd_check())
    elif sub == "fix":
        sys.exit(cmd_fix())
    elif sub == "test":
        sys.exit(cmd_test())
    else:
        print("用法: python ledger.py [check|fix|test]")
        print("  check  只读检查表结构（推荐先跑）")
        print("  fix    自动建表/建字段/修复类型错误字段")
        print("  test   修复 + 写入测试行验证链路后删除（默认）")
        sys.exit(2)
