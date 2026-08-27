# -*- coding: utf-8 -*-
# 这是 config.py 的模板。复制为 config.py 并填入真实信息后使用。
# 注意：config.py 含密码，已被 .gitignore 忽略，请勿提交 / 上传到公开仓库。

# 分批账号：每个子列表为一批。运行时 `python rainyun.py N` 执行第 N 批。
ACCOUNTS = [
    [  # 第 0 批
        ("username1", "password1"),
        ("username2", "password2"),
    ],
    # 继续按批添加...
]

# 飞书多维表格记账（雨云签到记录）
LEDGER_ENABLED = True
LARK_APP_ID = "your_app_id"
LARK_APP_SECRET = "your_app_secret"
LARK_APP_TOKEN = "your_base_app_token"
LARK_TABLE_ID = "tblxxxxxxxxxxxxxx"

# PushPlus 微信推送（notify.py 的 PUSH_PLUS_TOKEN）
PUSH_PLUS_TOKEN = "your_pushplus_token"
