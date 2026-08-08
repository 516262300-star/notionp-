from __future__ import annotations

import json
import logging
import os
import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Iterable
from urllib.parse import parse_qsl, urljoin, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from consumer_experience import ConsumerExperience
from date_utils import SHANGHAI_TZ, WeekPeriod
from erp_session import load_session, save_session
from store_overview import StoreOverview, decimal_value


BASE_URL = "https://ldswj.net"
LOGIN_PAGE_URL = f"{BASE_URL}/leedis/index.php/login/profile"
LOGIN_ACTION_URL = f"{BASE_URL}/leedis/index.php/welcome/loginact"
SMS_URL = f"{BASE_URL}/leedis/index.php/fileupload/sms"
EFFECTIVE_URL = f"{BASE_URL}/leedis2/public/effectivemonth"
EFFECTIVE_DETAIL_DATA_URL = f"{BASE_URL}/leedis2/public/salesamtkb/detail-data"
EFFECTIVE_MONTHLY_TABLE_URL = f"{EFFECTIVE_URL}/monthlytable"
EFFECTIVE_BLINE_DETAIL_URL = f"{EFFECTIVE_URL}/blinedetail"
TMALL_AD_URL = (
    f"{BASE_URL}/leedis2/public/admanager?action=ad_tmall_data&platform=1&store=103"
)
TAOBAO_AD_URL = (
    f"{BASE_URL}/leedis2/public/admanager?action=ad_tbx_data&platform=26&store=26"
)
PDD_OVERVIEW_URL = f"{BASE_URL}/leedis/index.php/alidata/stdview"


class ErpError(RuntimeError):
    pass


class ErpLoginRequired(ErpError):
    pass


class ErpParseError(ErpError):
    pass


@dataclass(frozen=True)
class AdTotal:
    revenue: float | None
    cost: float | None


@dataclass(frozen=True)
class EffectiveTotal:
    effective_sales: float | None
    shipping_gross_profit: float | None
    shipping_net_profit: float | None


PDD_STORE_ALIASES = {
    "一店": ("1店", "利德仕官方旗舰店"),
    "二店": ("2店", "LEEDIS官方旗舰店"),
    "三店": ("3店", "利德仕旗舰店"),
    "四店": ("4店", "珂琪艺官方旗舰店"),
    "五店": ("5店", "固家恒五金旗舰店"),
    "六店": ("6店", "梵居匠五金旗舰店"),
    "七店": ("7店", "适家旗舰店"),
}
SPECIAL_ALIASES = {
    "淘宝": ("淘宝项目",),
    "天猫": ("3店", "珂琪艺旗舰店"),
    "私域": ("私域总计",),
}


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def _number(value: str) -> float | None:
    text = _normal_text(value)
    if text in {"", "-", "—", "--", "null", "None"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    if cleaned in {"", "-", ".", "-."}:
        return None
    result = float(cleaned)
    return -abs(result) if negative else result


def _first_matching_index(headers: list[str], candidates: Iterable[str]) -> int | None:
    normalized = [_normal_text(header) for header in headers]
    for candidate in candidates:
        candidate_text = _normal_text(candidate)
        for index, header in enumerate(normalized):
            if candidate_text == header or candidate_text in header:
                return index
    return None


def _cookie_payload(client: httpx.Client) -> list[dict[str, Any]]:
    return [
        {
            "name": cookie.name,
            "value": cookie.value,
            "domain": cookie.domain,
            "path": cookie.path,
            "secure": bool(cookie.secure),
            "expires": cookie.expires,
        }
        for cookie in client.cookies.jar
    ]


class ErpClient:
    def __init__(self) -> None:
        load_dotenv()
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=45,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/138 Safari/537.36"
                )
            },
        )
        payload = load_session() or {}
        for cookie in payload.get("cookies", []):
            self.client.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain") or "ldswj.net",
                path=cookie.get("path") or "/",
            )

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "ErpClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _save(self) -> None:
        save_session(
            {
                "saved_at": datetime.now(SHANGHAI_TZ).isoformat(),
                "cookies": _cookie_payload(self.client),
            }
        )

    @staticmethod
    def _is_login_page(response: httpx.Response) -> bool:
        text = response.text
        return (
            "/welcome/loginact" in text
            or "手机验证 登录" in text
            or "请输入动态码" in text
        )

    def send_sms(self, phone: str) -> None:
        phone = phone.strip()
        if not re.fullmatch(r"1\d{10}", phone):
            raise ErpError("手机号格式不正确")
        response = self.client.post(SMS_URL, data={"phonefromcus": phone})
        response.raise_for_status()
        try:
            result = response.json()
        except json.JSONDecodeError as exc:
            raise ErpError("系统没有返回可识别的短信发送结果") from exc
        if result != 2 and str(result) != "2":
            if result == 1 or str(result) == "1":
                raise ErpError("系统提示手机号错误")
            raise ErpError(f"系统短信发送失败：{result}")
        self._save()

    @staticmethod
    def configured_credentials() -> tuple[str, str] | None:
        phone = os.getenv("ERP_PHONE", "").strip()
        password = os.getenv("ERP_PASSWORD", "").strip()
        if phone and password:
            return phone, password
        return None

    def login(self, phone: str, password: str) -> None:
        phone = phone.strip()
        password = password.strip()
        if not re.fullmatch(r"1\d{10}", phone):
            raise ErpError("手机号格式不正确")
        if not password:
            raise ErpError("登录密码不能为空")
        response = self.client.post(LOGIN_ACTION_URL, data={"phone": phone, "password": password})
        response.raise_for_status()
        try:
            result = response.json()
        except json.JSONDecodeError as exc:
            raise ErpError("系统没有返回可识别的登录结果") from exc
        if isinstance(result, dict):
            result_code = result.get("code")
            message = result.get("mes") or result.get("message") or "登录失败"
        else:
            result_code = result
            message = str(result)
        if str(result_code) not in {"0", "2"}:
            raise ErpError(str(message))
        check = self.client.get(LOGIN_PAGE_URL)
        check.raise_for_status()
        if self._is_login_page(check):
            raise ErpError("账号或登录密码不正确")
        self._save()

    def check_login(self, *, auto_login: bool = True) -> bool:
        response = self.client.get(LOGIN_PAGE_URL)
        response.raise_for_status()
        logged_in = not self._is_login_page(response)
        if logged_in:
            self._save()
        elif auto_login and (credentials := self.configured_credentials()):
            self.login(*credentials)
            logged_in = True
        return logged_in

    def _get_authenticated(self, url: str, **kwargs: Any) -> httpx.Response:
        response = self.client.get(url, **kwargs)
        response.raise_for_status()
        if self._is_login_page(response):
            credentials = self.configured_credentials()
            if credentials:
                self.login(*credentials)
                response = self.client.get(url, **kwargs)
                response.raise_for_status()
            if self._is_login_page(response):
                raise ErpLoginRequired("系统登录已过期，请检查 .env 中的 ERP_PHONE 和 ERP_PASSWORD")
        self._save()
        return response

    @staticmethod
    def _format_like(value: str, target: date) -> str:
        if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", value or ""):
            return target.strftime("%Y/%m/%d")
        if re.fullmatch(r"\d{4}-\d{1,2}", value or ""):
            return target.strftime("%Y-%m")
        return target.isoformat()

    def _filtered_document(self, url: str, period: WeekPeriod) -> httpx.Response:
        initial = self._get_authenticated(url)
        soup = BeautifulSoup(initial.text, "html.parser")
        forms = soup.find_all("form")
        for form in forms:
            inputs = [element for element in form.find_all(["input", "select"]) if element.get("name")]
            date_inputs = [
                element
                for element in inputs
                if element.name == "input"
                and (
                    element.get("type") in {"date", "month"}
                    or re.fullmatch(r"\d{4}[-/]\d{1,2}([-/]\d{1,2})?", element.get("value", ""))
                )
            ]
            start_input = None
            end_input = None
            for element in inputs:
                name = element.get("name", "").lower().replace("_", "")
                if any(token in name for token in ("start", "begin", "from", "sdate", "date1", "stime")):
                    start_input = element
                if any(token in name for token in ("end", "stop", "to", "edate", "date2", "etime")):
                    end_input = element
            if start_input is None and len(date_inputs) >= 2:
                start_input = date_inputs[0]
            if end_input is None and len(date_inputs) >= 2:
                end_input = date_inputs[1]
            if start_input is None or end_input is None:
                continue

            data: dict[str, str] = {}
            for element in inputs:
                name = element.get("name")
                if not name:
                    continue
                if element.name == "select":
                    selected = element.find("option", selected=True) or element.find("option")
                    data[name] = "" if selected is None else selected.get("value", selected.get_text(strip=True))
                elif element.get("type") not in {"submit", "button", "reset", "file"}:
                    data[name] = element.get("value", "")
            data[start_input["name"]] = self._format_like(start_input.get("value", ""), period.start_date)
            data[end_input["name"]] = self._format_like(end_input.get("value", ""), period.end_date)
            action = urljoin(str(initial.url), form.get("action") or str(initial.url))
            method = (form.get("method") or "get").lower()
            if method == "post":
                response = self.client.post(action, data=data)
            else:
                response = self.client.get(action, params=data)
            response.raise_for_status()
            if self._is_login_page(response):
                raise ErpLoginRequired("系统登录已过期，请检查 .env 中的 ERP_PHONE 和 ERP_PASSWORD")
            self._save()
            return response

        logging.warning("网页未发现起止日期表单，将按页面支持的月份参数查询")
        parsed_url = urlsplit(url)
        params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        params.update(
            {
                "ym": period.start_date.strftime("%Y-%m"),
                "start_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
            }
        )
        base_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", parsed_url.fragment))
        return self._get_authenticated(
            base_url,
            params=params,
        )

    def _documents_with_iframes(self, response: httpx.Response) -> list[str]:
        documents = [response.text]
        soup = BeautifulSoup(response.text, "html.parser")
        for iframe in soup.find_all("iframe", src=True):
            iframe_url = urljoin(str(response.url), iframe["src"])
            try:
                iframe_response = self._get_authenticated(iframe_url)
            except (httpx.HTTPError, ErpError) as exc:
                logging.warning("读取系统内嵌报表失败：%s", exc)
                continue
            documents.append(iframe_response.text)
        return documents

    @staticmethod
    def _tables(documents: Iterable[str]) -> list[tuple[list[str], list[list[str]]]]:
        result: list[tuple[list[str], list[list[str]]]] = []
        for html in documents:
            soup = BeautifulSoup(html, "html.parser")
            for table in soup.find_all("table"):
                rows = []
                for tr in table.find_all("tr"):
                    cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
                    if cells:
                        rows.append(cells)
                if len(rows) < 2:
                    continue
                header_index = next(
                    (index for index, row in enumerate(rows) if any("项目" in cell or "广告" in cell for cell in row)),
                    0,
                )
                result.append((rows[header_index], rows[header_index + 1 :]))
        return result

    @staticmethod
    def _row_matches(row: list[str], aliases: tuple[str, ...]) -> bool:
        joined = _normal_text(" ".join(row))
        return all(_normal_text(alias) in joined for alias in aliases)

    @staticmethod
    def _max_page(response: httpx.Response) -> int:
        soup = BeautifulSoup(response.text, "html.parser")
        pages = [1]
        for anchor in soup.find_all("a", href=True):
            query = dict(parse_qsl(urlsplit(urljoin(str(response.url), anchor["href"])).query))
            try:
                pages.append(int(query.get("page", "1")))
            except ValueError:
                continue
        return max(pages)

    @staticmethod
    def _ad_values_from_response(response: httpx.Response, period: WeekPeriod) -> tuple[float, float, bool]:
        cost_total = 0.0
        revenue_total = 0.0
        found_schema = False
        for headers, rows in ErpClient._tables([response.text]):
            cost_index = _first_matching_index(headers, ("广告费", "总花费", "花费", "消耗"))
            revenue_index = _first_matching_index(headers, ("广告成交金额", "广告成交", "成交额", "成交金额"))
            date_index = _first_matching_index(headers, ("日期",))
            if cost_index is None or revenue_index is None:
                continue
            found_schema = True
            for row in rows:
                required_indexes = [cost_index, revenue_index]
                if date_index is not None:
                    required_indexes.append(date_index)
                if max(required_indexes) >= len(row):
                    continue
                if date_index is not None:
                    match = re.search(r"(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)", row[date_index])
                    if not match:
                        continue
                    row_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                    if not period.start_date <= row_date <= period.end_date:
                        continue
                cost_total += _number(row[cost_index]) or 0.0
                revenue_total += _number(row[revenue_index]) or 0.0
        return cost_total, revenue_total, found_schema

    def fetch_ad_total(self, url: str, period: WeekPeriod) -> AdTotal:
        parsed_url = urlsplit(url)
        base_url = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))
        params = dict(parse_qsl(parsed_url.query, keep_blank_values=True))
        params.update(
            {
                "begin_date": period.start_date.isoformat(),
                "end_date": period.end_date.isoformat(),
                "page": "1",
            }
        )
        first_response = self._get_authenticated(base_url, params=params)
        max_page = self._max_page(first_response)
        responses = [first_response]
        for page in range(2, max_page + 1):
            params["page"] = str(page)
            responses.append(self._get_authenticated(base_url, params=params))

        cost_total = 0.0
        revenue_total = 0.0
        found_schema = False
        for response in responses:
            cost, revenue, page_has_schema = self._ad_values_from_response(response, period)
            cost_total += cost
            revenue_total += revenue
            found_schema = found_schema or page_has_schema
        if not found_schema:
            raise ErpParseError("广告页面没有找到广告费和广告成交列")
        logging.info(
            "广告明细读取：%s 到 %s，共 %s 页，广告费=%s，广告成交=%s",
            period.start_date,
            period.end_date,
            max_page,
            round(cost_total, 2),
            round(revenue_total, 2),
        )
        return AdTotal(revenue=round(revenue_total, 2), cost=round(cost_total, 2))

    @staticmethod
    def _overview_value(html: str, target_date: date, candidates: Iterable[str]) -> str | None:
        for headers, rows in ErpClient._tables([html]):
            value_index = _first_matching_index(headers, candidates)
            date_index = _first_matching_index(headers, ("日期",))
            if value_index is None or date_index is None:
                continue
            for row in rows:
                if max(value_index, date_index) >= len(row):
                    continue
                if row[date_index].strip() == target_date.isoformat():
                    return row[value_index]
        return None

    def fetch_pdd_store_metrics(
        self,
        target_date: date,
    ) -> tuple[list[StoreOverview], list[ConsumerExperience]]:
        overview_result: list[StoreOverview] = []
        experience_result: list[ConsumerExperience] = []
        for shop_index, shop_name in enumerate(PDD_STORE_ALIASES, start=1):
            response = self._get_authenticated(
                PDD_OVERVIEW_URL,
                params={
                    "platform": "pdddata",
                    "store": str(shop_index),
                    "startdate": target_date.isoformat(),
                    "enddate": target_date.isoformat(),
                },
            )
            overview_values = {
                "experience_star": self._overview_value(
                    response.text, target_date, ("综合体验星级",)
                ),
                "growth_level": self._overview_value(response.text, target_date, ("成长层级",)),
                "rating_score": self._overview_value(response.text, target_date, ("店铺评价分",)),
                "service_score": self._overview_value(
                    response.text, target_date, ("消费者服务体验分",)
                ),
            }
            if all(value is None for value in overview_values.values()):
                raise ErpParseError(f"{shop_name}在 {target_date} 没有店铺概况数据")
            overview = StoreOverview(
                shop_name=shop_name,
                experience_star=decimal_value(overview_values["experience_star"] or ""),
                growth_level=decimal_value(overview_values["growth_level"] or ""),
                rating_score=decimal_value(
                    overview_values["rating_score"] or "", zero_is_missing=True
                ),
                service_score=decimal_value(overview_values["service_score"] or ""),
            )
            consumer_values = {
                "overall_score": self._overview_value(
                    response.text, target_date, ("消费者服务体验分",)
                ),
                "attitude_score": self._overview_value(
                    response.text, target_date, ("服务态度体验分",)
                ),
                "basic_score": self._overview_value(
                    response.text, target_date, ("基础服务体验分",)
                ),
                "shipping_score": self._overview_value(
                    response.text, target_date, ("发货服务体验分",)
                ),
                "product_score": self._overview_value(
                    response.text, target_date, ("商品服务体验分",)
                ),
                "logistics_score": self._overview_value(
                    response.text, target_date, ("物流服务体验分",)
                ),
            }
            if all(value is None for value in consumer_values.values()):
                raise ErpParseError(f"{shop_name}在 {target_date} 没有消费者体验分数据")
            experience = ConsumerExperience(
                shop_name=shop_name,
                **{
                    field: decimal_value(value or "")
                    for field, value in consumer_values.items()
                },
            )
            overview_result.append(overview)
            experience_result.append(experience)
            logging.info("店铺概况读取：%s，日期=%s，数据=%s", shop_name, target_date, overview)
            logging.info(
                "消费者体验分读取：%s，日期=%s，数据=%s",
                shop_name,
                target_date,
                experience,
            )
        return overview_result, experience_result

    def fetch_store_overviews(self, target_date: date) -> list[StoreOverview]:
        overviews, _ = self.fetch_pdd_store_metrics(target_date)
        return overviews

    @staticmethod
    def _effective_from_summary(
        tables: list[tuple[list[str], list[list[str]]]],
    ) -> dict[str, EffectiveTotal]:
        result: dict[str, EffectiveTotal] = {}
        aliases = {**PDD_STORE_ALIASES, **SPECIAL_ALIASES}
        for headers, rows in tables:
            sales_index = _first_matching_index(headers, ("有效销售",))
            gross_index = _first_matching_index(headers, ("发货毛利",))
            net_index = _first_matching_index(headers, ("发货净利",))
            if sales_index is None or gross_index is None or net_index is None:
                continue
            for name, name_aliases in aliases.items():
                for row in rows:
                    if max(sales_index, gross_index, net_index) >= len(row):
                        continue
                    if ErpClient._row_matches(row, name_aliases):
                        result[name] = EffectiveTotal(
                            effective_sales=_number(row[sales_index]),
                            shipping_gross_profit=_number(row[gross_index]),
                            shipping_net_profit=_number(row[net_index]),
                        )
                        break
        return result

    @staticmethod
    def _effective_from_details(
        tables: list[tuple[list[str], list[list[str]]]],
        period: WeekPeriod,
    ) -> dict[str, EffectiveTotal]:
        aliases = {**PDD_STORE_ALIASES, **SPECIAL_ALIASES}
        sums: dict[str, list[float]] = {name: [0.0, 0.0, 0.0] for name in aliases}
        matched: set[str] = set()
        for headers, rows in tables:
            date_index = _first_matching_index(headers, ("日期", "发货日期", "下单日期"))
            sales_index = _first_matching_index(headers, ("有效销售",))
            gross_index = _first_matching_index(headers, ("发货毛利",))
            net_index = _first_matching_index(headers, ("发货净利",))
            if None in {date_index, sales_index, gross_index, net_index}:
                continue
            assert date_index is not None and sales_index is not None and gross_index is not None and net_index is not None
            for row in rows:
                if max(date_index, sales_index, gross_index, net_index) >= len(row):
                    continue
                match = re.search(r"(20\d{2})[-/]([01]?\d)[-/]([0-3]?\d)", row[date_index])
                if not match:
                    continue
                row_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                if not period.start_date <= row_date <= period.end_date:
                    continue
                for name, name_aliases in aliases.items():
                    if ErpClient._row_matches(row, name_aliases):
                        values = sums[name]
                        values[0] += _number(row[sales_index]) or 0.0
                        values[1] += _number(row[gross_index]) or 0.0
                        values[2] += _number(row[net_index]) or 0.0
                        matched.add(name)
                        break
        return {
            name: EffectiveTotal(round(values[0], 2), round(values[1], 2), round(values[2], 2))
            for name, values in sums.items()
            if name in matched
        }

    @staticmethod
    def _month_segments(period: WeekPeriod) -> list[tuple[date, date]]:
        segments: list[tuple[date, date]] = []
        cursor = period.start_date
        while cursor <= period.end_date:
            month_end = date(cursor.year, cursor.month, monthrange(cursor.year, cursor.month)[1])
            segment_end = min(month_end, period.end_date)
            segments.append((cursor, segment_end))
            cursor = segment_end.replace(day=1)
            if segment_end == period.end_date:
                break
            cursor = date(
                segment_end.year + (1 if segment_end.month == 12 else 0),
                1 if segment_end.month == 12 else segment_end.month + 1,
                1,
            )
        return segments

    def _effective_detail_rows(self, period: WeekPeriod) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        page_size = 1000
        draw = 1
        for segment_start, segment_end in self._month_segments(period):
            offset = 0
            total: int | None = None
            while total is None or offset < total:
                params = {
                    "draw": str(draw),
                    "start": str(offset),
                    "length": str(page_size),
                    "search[value]": "",
                    "search[regex]": "false",
                    "filter_start": segment_start.isoformat(),
                    "filter_end": segment_end.isoformat(),
                    "ym": segment_start.strftime("%Y-%m"),
                    "salesman": "",
                    "platform": "",
                    "businessline": "",
                }
                response = self._get_authenticated(EFFECTIVE_DETAIL_DATA_URL, params=params)
                try:
                    payload = response.json()
                except json.JSONDecodeError as exc:
                    raise ErpParseError("有效销售明细接口没有返回 JSON 数据") from exc
                page_rows = payload.get("data")
                if not isinstance(page_rows, list):
                    raise ErpParseError("有效销售明细接口缺少 data 列表")
                try:
                    total = int(payload.get("recordsFiltered", 0))
                except (TypeError, ValueError) as exc:
                    raise ErpParseError("有效销售明细接口记录数格式错误") from exc
                rows.extend(row for row in page_rows if isinstance(row, dict))
                offset += len(page_rows)
                draw += 1
                if not page_rows:
                    break
            logging.info(
                "有效销售明细读取：%s 到 %s，共 %s 行",
                segment_start,
                segment_end,
                total or 0,
            )
        return rows

    @staticmethod
    def _effective_from_json_rows(rows: Iterable[dict[str, Any]]) -> dict[str, EffectiveTotal]:
        expected = [*PDD_STORE_ALIASES, *SPECIAL_ALIASES]
        sums: dict[str, list[float]] = {name: [0.0, 0.0, 0.0] for name in expected}

        for row in rows:
            business_line = _normal_text(str(row.get("业务线", "")))
            store = _normal_text(str(row.get("店铺", "")))
            source = _normal_text(str(row.get("单源", "")))
            target: str | None = None

            if business_line == "拼多多项目":
                for name, aliases in PDD_STORE_ALIASES.items():
                    if all(_normal_text(alias) in store for alias in aliases):
                        target = name
                        break
                if target is None and store == "1" and source in {"微信", "常规"}:
                    target = "私域"
            elif business_line == "淘宝项目":
                target = "淘宝"
            elif (
                business_line == "天猫项目"
                and "3店" in store
                and "珂琪艺旗舰店" in store
            ):
                target = "天猫"

            if target is None:
                continue
            values = sums[target]
            values[0] += _number(str(row.get("有效销售", ""))) or 0.0
            values[1] += _number(str(row.get("发货毛利", ""))) or 0.0
            values[2] += _number(str(row.get("发货净利", ""))) or 0.0

        return {
            name: EffectiveTotal(
                effective_sales=round(values[0], 2),
                shipping_gross_profit=round(values[1], 2),
                shipping_net_profit=round(values[2], 2),
            )
            for name, values in sums.items()
        }

    @staticmethod
    def _business_summary_month(period: WeekPeriod) -> str:
        if (period.start_date.year, period.start_date.month) != (
            period.end_date.year,
            period.end_date.month,
        ):
            raise ErpParseError("有效销售-业务线汇总只支持选择月份，不能读取跨月区间")

        today = datetime.now(SHANGHAI_TZ).date()
        month_last_day = monthrange(period.start_date.year, period.start_date.month)[1]
        current_month_cutoffs = {today}
        yesterday = today - timedelta(days=1)
        if (yesterday.year, yesterday.month) == (today.year, today.month):
            current_month_cutoffs.add(yesterday)
        is_current_month_to_date = (
            (period.start_date.year, period.start_date.month) == (today.year, today.month)
            and period.start_date.day == 1
            and period.end_date in current_month_cutoffs
        )
        is_closed_full_month = (
            period.start_date.day == 1
            and period.end_date.day == month_last_day
            and period.end_date < today
        )
        if not (is_current_month_to_date or is_closed_full_month):
            current_hint = date(today.year, today.month, 1)
            raise ErpParseError(
                "有效销售-业务线汇总只有月份筛选，无法精确生成所选日期区间。"
                f"当前可用的月累计区间是 {current_hint} 到昨天或今天；"
                "历史月份必须选择该月1日到月末。"
            )
        return period.start_date.strftime("%Y-%m")

    @staticmethod
    def _html_rows(response: httpx.Response) -> list[list[str]]:
        soup = BeautifulSoup(response.text, "html.parser")
        rows: list[list[str]] = []
        for tr in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)
        return rows

    @staticmethod
    def _find_named_row(rows: Iterable[list[str]], aliases: tuple[str, ...]) -> list[str]:
        for row in rows:
            if len(row) < 2:
                continue
            name = _normal_text(row[1])
            if all(_normal_text(alias) in name for alias in aliases):
                return row
        raise ErpParseError(f"有效销售-业务线汇总缺少项目：{' / '.join(aliases)}")

    @staticmethod
    def _effective_from_shipping_row(row: list[str]) -> EffectiveTotal:
        if len(row) < 12:
            raise ErpParseError(f"业务线汇总店铺行字段不足：{row[1] if len(row) > 1 else '未知项目'}")
        return EffectiveTotal(
            effective_sales=_number(row[2]) or 0.0,
            shipping_gross_profit=_number(row[10]) or 0.0,
            shipping_net_profit=_number(row[11]) or 0.0,
        )

    def _business_line_detail_rows(self, business_line_code: str, year_month: str) -> list[list[str]]:
        response = self._get_authenticated(
            EFFECTIVE_BLINE_DETAIL_URL,
            params={"bl": business_line_code, "ym": year_month},
        )
        return self._html_rows(response)

    def _effective_from_business_line_summary(self, period: WeekPeriod) -> dict[str, EffectiveTotal]:
        year_month = self._business_summary_month(period)
        summary_response = self._get_authenticated(
            EFFECTIVE_MONTHLY_TABLE_URL,
            params={"by": "bl", "headless": "1", "ym": year_month},
        )
        summary_rows = self._html_rows(summary_response)
        pdd_rows = self._business_line_detail_rows("3", year_month)
        tmall_rows = self._business_line_detail_rows("2", year_month)

        result = {
            name: self._effective_from_shipping_row(self._find_named_row(pdd_rows, aliases))
            for name, aliases in PDD_STORE_ALIASES.items()
        }
        result["淘宝"] = self._effective_from_shipping_row(
            self._find_named_row(summary_rows, ("淘宝项目",))
        )
        result["天猫"] = self._effective_from_shipping_row(
            self._find_named_row(tmall_rows, ("3店", "珂琪艺旗舰店"))
        )

        private_row = self._find_named_row(pdd_rows, ("私域总计",))
        if len(private_row) < 5:
            raise ErpParseError("拼多多项目的私域总计字段不足")
        # 业务线汇总的私域总计没有“发货毛利/发货净利”两列，利润模板沿用
        # 该行的“毛利/净利”作为私域的发货毛利/发货净利口径。
        result["私域"] = EffectiveTotal(
            effective_sales=_number(private_row[2]) or 0.0,
            shipping_gross_profit=_number(private_row[3]) or 0.0,
            shipping_net_profit=_number(private_row[4]) or 0.0,
        )
        logging.info("有效销售业务线汇总读取完成：月份=%s", year_month)
        return result

    def fetch_effective_totals(self, period: WeekPeriod) -> dict[str, EffectiveTotal]:
        return self._effective_from_business_line_summary(period)

    def fetch_tmall_ad_total(self, period: WeekPeriod) -> AdTotal:
        return self.fetch_ad_total(TMALL_AD_URL, period)

    def fetch_taobao_ad_total(self, period: WeekPeriod) -> AdTotal:
        return self.fetch_ad_total(TAOBAO_AD_URL, period)
