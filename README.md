# 拼多多周报本地生成脚本

这个项目用本地 Python 调用 Notion 官方 API，按可选日期生成「拼多多2026周报」页面，在「广告情况」下创建 7 个店铺的内嵌数据库，并在「盈亏情况」下创建利润数据库。

## 环境要求

- Python 3.11+
- Notion Integration Token，并已给相关页面和数据库授权
- 可访问利德仕系统的手机号和长期登录密码（网站称“验证码”）。账号密码保存在本机 `.env`，不会提交到 GitHub
- 所有日期计算使用 `Asia/Shanghai`。Windows 通常需要安装 `tzdata`，已写入 `requirements.txt`；如果运行环境缺少系统时区库或 `tzdata`，脚本会自动退回 UTC+8，避免启动阶段报 `ZoneInfoNotFoundError`
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

利德仕系统登录配置：

- `ERP_PHONE`：利德仕系统登录手机号。
- `ERP_PASSWORD`：利德仕系统长期登录密码（网站界面称“验证码”）。

填写以上两项后，桌面生成器会自动带出账号密码；已保存的网站会话过期时，也会自动重新登录。

## 本地运行

先做只读连接测试：

```powershell
python test_connection.py
```

测试通过后再生成周报：

```powershell
python main.py
```

指定任意起止日期：

```powershell
python main.py --start-date 2026-08-01 --end-date 2026-08-07
```

只检查和汇总盈亏数据、不写入 Notion：

```powershell
python main.py --start-date 2026-08-01 --end-date 2026-08-07 --dry-run
```

## 桌面软件

桌面上已经创建了快捷方式，目标指向无控制台启动器：

```text
拼多多周报生成器.lnk
```

双击后会打开图形界面，可以直接点：

- `上一整周`、`本月至今`、`本月整月`，或手工填写起止日期
- `获取/重置验证码`、`登录系统`、`检查登录`
- `测试连接`
- `生成正式周报`
- `打开项目文件夹`

如果从项目文件夹启动，双击 `启动拼多多周报生成器.vbs`；它会隐藏后面的黑色命令行窗口。

不填写命令行日期时，脚本仍默认计算上周一到上周日。完整周的标题格式示例：

```text
2026时间：第二十三周2026年6月1日到2026年6月7日
```

重复运行同一周时，不会重复创建周报页面；如果页面存在但 7 个店铺内嵌数据库不齐，会自动补齐缺失的店铺表。

自定义日期不是完整的周一至周日时，标题只显示起止日期，不误标 ISO 周数，例如：

```text
2026时间：2026年8月1日到2026年8月7日
```

## 利德仕系统登录

淘宝、天猫和有效销售数据来自利德仕系统。网页登录使用手机号和长期登录密码，网站把该密码称为“验证码”。请在本机 `.env` 填写：

```dotenv
ERP_PHONE=你的手机号
ERP_PASSWORD=你的登录密码
```

推荐操作：

1. 打开桌面生成器。
2. 确认自动带出的手机号和登录密码；如需首次获取或重置，可点 `获取/重置验证码`。
3. 点 `登录系统`。
4. 点 `检查登录`，看到“系统登录状态正常”。
5. 选择日期并生成周报。

登录成功后，网站 Cookie 会保存到本机 `.erp_session.bin`。该文件由 Windows DPAPI 按当前 Windows 用户加密，已加入 `.gitignore`，不能复制到其他电脑或其他 Windows 账号使用。会话过期后，生成周报时会优先使用 `.env` 中的账号密码自动重新登录。

命令行登录方式：

```powershell
python erp_login.py send-code --phone 你的手机号
python erp_login.py login --phone 你的手机号 --password 你的登录密码
python erp_login.py status
```

如果 `.env` 已填写 `ERP_PHONE` 和 `ERP_PASSWORD`，登录命令可直接写成 `python erp_login.py login`。

## 盈亏情况数据库

生成器会在周报的 `盈亏情况` 标题下面创建一个内嵌数据库，行顺序为：一店至七店、淘宝、天猫、私域、总计。

字段顺序：

```text
项目 → 广告成交 → 广告费 → ROI → 广告占比 → 发货净利 → 毛利-广告 → 有效销售 → 发货毛利
```

数据来源：

- 拼多多一店至七店的广告费、广告成交：Notion 七个每日广告数据库，按所选日期过滤后汇总。
- 淘宝广告费、广告成交：利德仕系统淘宝广告页面。
- 天猫广告费、广告成交：利德仕系统天猫广告页面中的 3店【珂琪艺旗舰店】。
- 有效销售、发货毛利、发货净利：利德仕系统“有效销售 - 明细”的数据接口，使用所选起止日期精确过滤后汇总。
- 私域：拼多多项目里的“私域总计”，广告字段留空。

计算口径：

- `ROI = 广告成交 ÷ 广告费`。
- `广告占比 = 广告费 ÷ 有效销售`。
- 有广告的店铺：`毛利-广告 = 发货毛利 - 广告费`。
- 私域没有广告数据，`毛利-广告`沿用模板口径，等于发货净利。
- 分母为 0 时比例留空，不生成除零错误。

有效销售数据不使用页面上会实时变化的月度汇总，而是读取带“完成日期”的明细接口。单周、整月、月中任意区间都按起止日期过滤；跨月区间会按月份拆段读取后再合并。淘宝和天猫广告页面使用 `begin_date / end_date` 精确筛选，并遍历全部分页；天猫固定取系统店铺参数 `103`，即 3店【珂琪艺旗舰店】。

## 日志

日志写入：

```text
logs/weekly_report_YYYYMMDD_HHMMSS.log
```

每次运行都会写入一个带时间戳的新日志文件，工作台只需要读取 `logs` 目录下最新的 `weekly_report_*.log`，即可判断最近一次运行结果；同一天早些时候的失败日志不会再影响后续成功运行的状态。

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

- Notion 请求采用与拼多多广告同步相同的网络容错：优先使用 Windows `curl.exe`/Schannel 直连，失败后尝试 Python 直连，最后尝试 `.env` 的 `NOTION_PROXY`（未配置时读取 Windows 系统代理）。成功路线会成为后续请求的首选。三条路线都失败时才进入调用重试；若仍出现 `SSL: UNEXPECTED_EOF_WHILE_READING` 或 `WinError 10054`，请检查 `curl.exe`、`api.notion.com` 和 Clash 节点。
- 源数据库按 `日期` 过滤上周周期。
- 日期可通过桌面生成器或 `--start-date`、`--end-date` 参数选择；命令行不传日期时仍取上一整周。
- 盈亏数据会在创建 Notion 页面前先完整抓取；网站登录失效或字段解析失败时不会创建半成品周报。
- 稳定成本按 `商品ID` 聚合，商品行按本周总花费降序排列。
- `投产`、`每笔成交花费`、`每笔成交金额` 遇到 0 或空分母时留空，避免 `ZeroDivisionError`。
- 主图 Relation 查询 `MAIN_IMAGE_DB_ID` 的标题属性 `商品ID`；找不到时会在当周周报「其他问题反馈」下追加缺主图提示。
- 只有脚本崩溃才会向 `ALERT_PAGE_ID` 追加红色 callout，并用 Notion mention 真实 @ `NOTIFY_USER_ID`。
- 如果运行面板显示 `No module named 'tzdata'` 或 `No time zone found with key Asia/Shanghai`，优先确认任务计划程序或启动器使用的是 `.venv\Scripts\python.exe`；当前代码也会在缺少 `tzdata` 时退回 UTC+8 继续运行。
