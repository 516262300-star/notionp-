# 拼多多周报本地生成脚本

这个项目用本地 Python 调用 Notion 官方 API，按周生成「拼多多2026周报」页面，并在「广告情况」下创建 7 个店铺的内嵌数据库。

## 环境要求

- Python 3.11+
- Notion Integration Token，并已给相关页面和数据库授权
- 所有日期计算使用 `Asia/Shanghai`。Windows 通常需要安装 `tzdata`，已写入 `requirements.txt`
- Notion API 版本：`2022-06-28`

## 安装

```powershell
cd D:\desktop\codex\notion拼多多周报\pdd_weekly_report
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env`，填入真实 ID：

```powershell
Copy-Item .env.example .env
notepad .env
```

必填项：

- `NOTION_TOKEN`：Notion Integration Token
- `PARENT_PAGE_ID`：「拼多多2026周报」父页面 ID
- `MAIN_IMAGE_DB_ID`：「广告链接主图」数据库 ID
- `SHOP_1_DB_ID` 到 `SHOP_7_DB_ID`：7 个店铺的每日广告数据数据库 ID
- `NOTIFY_USER_ID`：崩溃告警要 @ 的 Notion 用户 ID
- `ALERT_PAGE_ID`：收集脚本崩溃告警的 Notion 页面 ID

## 本地运行

先做只读连接测试：

```powershell
python test_connection.py
```

测试通过后再生成周报：

```powershell
python main.py
```

## 桌面软件

桌面上已经创建了快捷方式，目标指向无控制台启动器：

```text
拼多多周报生成器.lnk
```

双击后会打开图形界面，可以直接点：

- `测试连接`
- `生成正式周报`
- `打开项目文件夹`

如果从项目文件夹启动，优先双击 `启动拼多多周报生成器.vbs`；它会隐藏后面的黑色命令行窗口。`启动拼多多周报生成器.cmd` 仅作为兼容入口，会拉起图形界面后立即退出。

脚本会自动计算上周一到上周日，标题格式示例：

```text
2026时间：第二十三周2026年6月1日到2026年6月7日
```

重复运行同一周时，不会重复创建周报页面；如果页面存在但 7 个店铺内嵌数据库不齐，会自动补齐缺失的店铺表。

## 日志

日志写入：

```text
logs/weekly_report_YYYYMMDD.log
```

日志包含周报周期、重复检查结果、每个店铺源记录数、生成行数等信息。

## Windows 任务计划程序

1. 打开「任务计划程序」。
2. 选择「创建基本任务」。
3. 名称填写：`拼多多周报生成`。
4. 触发器选择「每周」，时间设为每周一 10:00。
5. 操作选择「启动程序」。
6. 程序或脚本填写虚拟环境里的 Python，例如：

```text
D:\desktop\codex\notion拼多多周报\pdd_weekly_report\.venv\Scripts\python.exe
```

7. 添加参数填写：

```text
main.py
```

8. 起始于填写：

```text
D:\desktop\codex\notion拼多多周报\pdd_weekly_report
```

## 维护说明

- 脚本不会读取系统环境变量里的代理（`httpx trust_env=False`），但会优先使用 `.env` 中的 `NOTION_PROXY`；未配置时会读取 Windows 系统代理。若出现 `SSL: UNEXPECTED_EOF_WHILE_READING` 或 `WinError 10054`，通常需要切换到可访问 Notion 的 Clash 节点，或把 `NOTION_PROXY` 改为可用端口。
- 源数据库按 `日期` 过滤上周周期。
- 稳定成本按 `商品ID` 聚合，商品行按本周总花费降序排列。
- `投产`、`每笔成交花费`、`每笔成交金额` 遇到 0 或空分母时留空，避免 `ZeroDivisionError`。
- 主图 Relation 查询 `MAIN_IMAGE_DB_ID` 的标题属性 `商品ID`；找不到时会在当周周报「其他问题反馈」下追加缺主图提示。
- 只有脚本崩溃才会向 `ALERT_PAGE_ID` 追加红色 callout，并用 Notion mention 真实 @ `NOTIFY_USER_ID`。
