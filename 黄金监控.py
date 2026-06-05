import requests
import time
import json
import os
import sys
import logging
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from logging.handlers import RotatingFileHandler  # 新增：日志轮转支持
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

class Config:
    def __init__(self):
        self.webhooks = []
        self.symbols = {}
        self.check_interval = 300
        self.time_periods = {}
        self.weekend_check = False
        self.max_history_days = 30
        self.log_file = "monitor.log"
        self.log_level = "INFO"
        self.data_file = "gold_data.json"
        self.prediction_file = "predictions.json"
        self.web_dashboard = {"enabled": False, "port": 8080}
        self.domestic_gold = {"name": "国内黄金", "unit": "元/克", "enabled": True}
        self.load()

    def load(self):
        cfg = {}
        if os.path.exists(CONFIG_FILE):
            try:  # 修复：配置文件格式错误时捕获异常
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
            except json.JSONDecodeError as e:
                print(f"配置文件格式错误: {e}，使用默认配置")
                return
        self.webhooks = cfg.get("webhooks", [])
        self.symbols = cfg.get("symbols", {})
        self.check_interval = cfg.get("check_interval", 300)
        if self.check_interval <= 0:
            print(f"check_interval={self.check_interval} 无效，使用默认值300秒")
            self.check_interval = 300
        self.time_periods = cfg.get("time_periods", {})
        self.weekend_check = cfg.get("weekend_check", False)
        self.max_history_days = cfg.get("max_history_days", 30)
        if self.max_history_days <= 0:
            print(f"max_history_days={self.max_history_days} 无效，使用默认值30天")
            self.max_history_days = 30
        self.log_file = cfg.get("log_file", "monitor.log")
        self.log_level = cfg.get("log_level", "INFO")
        self.data_file = cfg.get("data_file", "gold_data.json")
        self.prediction_file = cfg.get("prediction_file", "predictions.json")
        self.web_dashboard = cfg.get("web_dashboard", {"enabled": False, "port": 8080})
        self.domestic_gold = cfg.get("domestic_gold", {"name": "国内黄金", "unit": "元/克", "enabled": True})
        # 环境变量覆盖：支持从环境变量读取 webhook（用于 GitHub Actions）
        env_webhook = os.environ.get("FEISHU_WEBHOOK")
        if env_webhook:
            self.webhooks = [env_webhook]

config = Config()

logger = logging.getLogger("GoldMonitor")
logger.setLevel(getattr(logging, config.log_level, logging.INFO))

# 修复：使用 RotatingFileHandler 实现日志轮转，最大10MB，保留5个备份
file_handler = RotatingFileHandler(
    os.path.join(BASE_DIR, config.log_file),
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(console_handler)

def send_feishu(title, content):
    """发送飞书 webhook 消息"""
    results = []
    for webhook in config.webhooks:
        try:
            logger.info(f"正在发送到 webhook: {webhook[:50]}...")
            data = {
                "msg_type": "text",
                "content": {"text": f"{title}\n{content}"}
            }
            response = requests.post(webhook, json=data, timeout=10)
            if response.status_code == 200:
                logger.info(f"✅ Webhook 发送成功")
                results.append(True)
            else:
                logger.error(f"❌ Webhook 返回状态码: {response.status_code}, 响应: {response.text}")
                results.append(False)
        except Exception as e:
            logger.error(f"❌ Webhook 发送异常: {e}")
            results.append(False)
    return any(results) if results else False

def get_price_from_sina(code):
    url = f"https://hq.sinajs.cn/list={code}"
    headers = {"Referer": "https://finance.sina.com.cn"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            text = response.text
            if not text or '=' not in text:  # 修复：检查空响应
                return None
            data = text.split('=')[1].strip('";\n')
            if not data or ',' not in data:  # 修复：检查格式变化
                return None
            price_str = data.split(',')[0]
            if not price_str or price_str == '0':  # 修复：检查零值
                return None
            return float(price_str)
    except (ValueError, IndexError) as e:  # 修复：捕获解析异常
        logger.warning(f"Sina parse error: {e}")
    except Exception as e:
        logger.warning(f"Sina request error: {e}")
    return None

def get_price_from_metal_api(code):
    symbol_map = {"hf_GC": "XAU", "hf_SI": "XAG", "hf_CL": "CL"}
    symbol = symbol_map.get(code)
    if not symbol:
        return None
    try:
        url = f"https://api.metals.live/v1/spot/{symbol.lower()}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                price = data[0].get("price", 0)
                if price:  # 修复：验证价格非零
                    return float(price)
    except Exception as e:  # 修复：改为 except Exception，不捕获 KeyboardInterrupt
        logger.error(f"Metal API error: {e}")
    return None

def get_price_from_fallback(code):
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/XAU"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            rate = data.get("rates", {}).get("USD", 1)
            return rate * 100
    except Exception as e:  # 修复：改为 except Exception
        logger.error(f"Fallback API error: {e}")
    return None

# ==================== 国内金价数据源 ====================

def get_domestic_price_from_sina():
    """从新浪财经获取沪金主力合约价格（元/克）"""
    url = "https://hq.sinajs.cn/list=au_0"
    headers = {"Referer": "https://finance.sina.com.cn"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            text = response.text
            if not text or '=' not in text:
                return None
            data = text.split('=')[1].strip('";\n')
            if not data or ',' not in data:
                return None
            price_str = data.split(',')[0]
            if not price_str or price_str == '0':
                return None
            return float(price_str)
    except (ValueError, IndexError) as e:
        logger.warning(f"国内金价 Sina parse error: {e}")
    except Exception as e:
        logger.warning(f"国内金价 Sina request error: {e}")
    return None

def get_domestic_price_from_eastmoney():
    """从东方财富获取上海金交所 Au9999 价格（元/克）"""
    url = "https://push2.eastmoney.com/api/qt/stock/get"
    params = {
        "secid": "113.Au9999",
        "fields": "f43,f44,f45,f46,f170"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data and data.get("data"):
                price = data["data"].get("f43")
                if price and price > 0:
                    return float(price) / 100  # 东方财富返回的价格需要除以100
    except Exception as e:
        logger.warning(f"国内金价 Eastmoney error: {e}")
    return None

def get_domestic_price():
    """获取国内金价（元/克），带多重数据源故障转移"""
    sources = [
        ("Sina沪金", get_domestic_price_from_sina),
        ("东方财富Au9999", get_domestic_price_from_eastmoney),
    ]
    for name, fetcher in sources:
        try:
            price = fetcher()
            if price and price > 0:
                logger.info(f"国内金价 from {name}: ¥{price:.2f}/克")
                return price, name
        except Exception as e:
            logger.warning(f"国内金价源 {name} failed: {e}")

    # 兜底方案：用国际金价 × 汇率 ÷ 31.1035 换算
    try:
        intl_price = get_price("gold")
        rate = get_usdcny_rate()
        if intl_price and rate:
            converted = intl_price * rate / 31.1035
            logger.info(f"国内金价 from 国际价换算: ¥{converted:.2f}/克")
            return converted, "国际价换算"
    except Exception as e:
        logger.warning(f"国内金价换算失败: {e}")

    logger.error("所有国内金价数据源均失败")
    return None, None

# ==================== 汇率数据源 ====================

def get_usdcny_from_sina():
    """从新浪财经获取 USD/CNY 汇率"""
    url = "https://hq.sinajs.cn/list=fx_susdcny"
    headers = {"Referer": "https://finance.sina.com.cn"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            text = response.text
            if not text or '=' not in text:
                return None
            data = text.split('=')[1].strip('";\n')
            if not data or ',' not in data:
                return None
            # 新浪汇率数据格式：名称,当前价,...，取第二个字段
            parts = data.split(',')
            if len(parts) >= 2:
                rate_str = parts[1]
                if rate_str and rate_str != '0':
                    return float(rate_str)
    except (ValueError, IndexError) as e:
        logger.warning(f"汇率 Sina parse error: {e}")
    except Exception as e:
        logger.warning(f"汇率 Sina request error: {e}")
    return None

def get_usdcny_from_frankfurter():
    """从 Frankfurter API 获取 USD/CNY 汇率（免费无需 key）"""
    url = "https://api.frankfurter.app/latest?from=USD&to=CNY"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            rate = data.get("rates", {}).get("CNY")
            if rate:
                return float(rate)
    except Exception as e:
        logger.warning(f"汇率 Frankfurter error: {e}")
    return None

def get_usdcny_rate():
    """获取 USD/CNY 汇率，带多重数据源故障转移"""
    sources = [
        ("Sina汇率", get_usdcny_from_sina),
        ("Frankfurter", get_usdcny_from_frankfurter),
    ]
    for name, fetcher in sources:
        try:
            rate = fetcher()
            if rate and rate > 0:
                logger.info(f"USD/CNY from {name}: {rate:.4f}")
                return rate
        except Exception as e:
            logger.warning(f"汇率源 {name} failed: {e}")

    logger.error("所有汇率数据源均失败")
    return None

def get_price(symbol_key):
    symbol_cfg = config.symbols.get(symbol_key)
    if not symbol_cfg:
        return None

    code = symbol_cfg["code"]
    sources = [
        ("Sina", lambda: get_price_from_sina(code)),
        ("MetalAPI", lambda: get_price_from_metal_api(code)),
        ("Fallback", lambda: get_price_from_fallback(code))
    ]

    for name, fetcher in sources:
        try:
            price = fetcher()
            if price and price > 0:
                logger.info(f"Price from {name}: ${price:.2f}")
                return price
        except Exception as e:
            logger.warning(f"Source {name} failed: {e}")

    logger.error("All price sources failed")
    return None

def load_daily_data(symbol_key):
    data_file = os.path.join(BASE_DIR, f"{symbol_key}_data.json")
    if os.path.exists(data_file):
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:  # 修复：改为 except Exception
            logger.error(f"Load daily data error: {e}")
    return []

def save_daily_data(symbol_key, daily_data):
    data_file = os.path.join(BASE_DIR, f"{symbol_key}_data.json")
    try:
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(daily_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save data error: {e}")

def load_predictions():
    pred_file = os.path.join(BASE_DIR, config.prediction_file)
    if os.path.exists(pred_file):
        try:
            with open(pred_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:  # 修复：改为 except Exception
            logger.error(f"Load predictions error: {e}")
    return []

def save_prediction(symbol_key, date, prediction, actual_close=None, base_price=0):
    predictions = load_predictions()
    entry = {
        "symbol": symbol_key,
        "date": date,
        "prediction": prediction,
        "actual_close": actual_close,
        "base_price": base_price,  # 修复：保存基准价格用于准确率计算
        "verified": actual_close is not None
    }
    predictions.append(entry)
    if len(predictions) > 100:
        predictions = predictions[-100:]
    pred_file = os.path.join(BASE_DIR, config.prediction_file)
    try:
        with open(pred_file, 'w', encoding='utf-8') as f:
            json.dump(predictions, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Save prediction error: {e}")

def get_prediction_accuracy():
    predictions = load_predictions()
    verified = [p for p in predictions if p.get("verified") and p.get("actual_close")]
    if not verified:
        return "暂无已验证的预测数据"

    correct = 0
    for p in verified:
        pred = p["prediction"].lower()
        actual = p["actual_close"]
        base = p.get("base_price", 0)
        change = ((actual - base) / base * 100) if base else 0

        if "看涨" in pred or "偏多" in pred:
            if change > 0:
                correct += 1
        elif "看跌" in pred or "偏空" in pred:
            if change < 0:
                correct += 1
        elif "震荡" in pred:
            if abs(change) < 1:
                correct += 1

    accuracy = (correct / len(verified)) * 100
    return f"预测准确率: {accuracy:.1f}% ({correct}/{len(verified)})"

def analyze_trend(prices, base_price):
    # 修复：移除默认值 4720，必须传入实际 base_price
    if len(prices) < 2:
        return "数据不足，无法判断"
    if not base_price or base_price <= 0:
        return "基准价格无效，无法分析"

    current = prices[-1]
    change_percent = ((current - base_price) / base_price) * 100

    # 修复：动态计算支撑位和压力位，不再硬编码
    support = current * 0.99
    resistance = current * 1.01

    if change_percent > 5:
        trend = "强势上涨"
        guess = f"可能继续走高，上方压力位在{resistance:.2f}附近，建议关注回调风险"
    elif change_percent > 2:
        trend = "温和上涨"
        guess = f"市场情绪偏多，上方压力位在{resistance:.2f}附近，短期仍有上涨空间"
    elif change_percent > 0:
        trend = "小幅上涨"
        guess = f"稳中有升，区间{support:.2f}-{resistance:.2f}，短期可能维持震荡整理"
    elif change_percent > -2:
        trend = "小幅下跌"
        guess = f"短期调整，下方支撑位在{support:.2f}附近，中期仍看好"
    elif change_percent > -5:
        trend = "明显下跌"
        guess = f"下方支撑位在{support:.2f}附近，买盘支撑较强，中长期仍有配置价值"
    else:
        trend = "大幅下跌"
        guess = f"超跌反弹信号出现，支撑位在{support:.2f}附近，建议分批布局"

    return f"当前趋势: {trend}\n预测: {guess}"

def predict_tomorrow(daily_data, symbol_name=""):
    if len(daily_data) < 2:
        return "数据不足，至少需要2天数据才能预测"

    recent = daily_data[-7:]
    closes = [d["close"] for d in recent]
    opens = [d["open"] for d in recent]
    highs = [d["high"] for d in recent]
    lows = [d["low"] for d in recent]

    n = len(recent)
    avg_close = sum(closes) / n
    avg_range = sum((h - l) for h, l in zip(highs, lows)) / n

    up_days = sum(1 for i in range(1, n) if closes[i] > closes[i-1])
    down_days = n - 1 - up_days

    ma3 = sum(closes[-3:]) / 3 if n >= 3 else avg_close
    ma5 = sum(closes[-5:]) / 5 if n >= 5 else avg_close

    last_close = closes[-1]
    signals = []
    score = 0

    if ma3 > ma5:
        signals.append("短期均线(3日)上穿中期均线(5日)，多头信号")
        score += 2
    elif ma3 < ma5:
        signals.append("短期均线(3日)下穿中期均线(5日)，空头信号")
        score -= 2

    if up_days > down_days:
        signals.append(f"近{n-1}日上涨{up_days}天，多方占优")
        score += 1
    elif down_days > up_days:
        signals.append(f"近{n-1}日下跌{down_days}天，空方占优")
        score -= 1

    if closes[-1] > opens[-1]:
        signals.append("今日收阳线")
        score += 1
    else:
        signals.append("今日收阴线")
        score -= 1

    if n >= 3 and closes[-1] > closes[-2] > closes[-3]:
        signals.append("连续3日上涨，动能较强")
        score += 1
    elif n >= 3 and closes[-1] < closes[-2] < closes[-3]:
        signals.append("连续3日下跌，动能较弱")
        score -= 1

    if score >= 3:
        prediction = "看涨"
        confidence = "较高"
    elif score >= 1:
        prediction = "偏多"
        confidence = "一般"
    elif score <= -3:
        prediction = "看跌"
        confidence = "较高"
    elif score <= -1:
        prediction = "偏空"
        confidence = "一般"
    else:
        prediction = "震荡"
        confidence = "一般"

    predicted_high = last_close + avg_range * 0.5
    predicted_low = last_close - avg_range * 0.5

    # 修复：动态生成预测文本，不再硬编码
    if prediction == "看涨" or prediction == "偏多":
        prediction_detail = f"预测明日继续上涨，上方压力位在{predicted_high:.2f}附近"
    elif prediction == "看跌" or prediction == "偏空":
        prediction_detail = f"预测明日继续下跌，下方支撑位在{predicted_low:.2f}附近"
    else:
        prediction_detail = f"预测明日横盘震荡，区间{predicted_low:.2f}-{predicted_high:.2f}"

    lines = [
        f"明日预测: {prediction} (置信度: {confidence})",
        f"预测区间: ${predicted_low:.2f} - ${predicted_high:.2f}",
        f"3日均线: ${ma3:.2f}",
        f"5日均线: ${ma5:.2f}",
        f"",
        f"分析: {prediction_detail}",
        f"",
        f"技术信号:"
    ]
    for s in signals:
        lines.append(f"  - {s}")

    return "\n".join(lines)

def generate_price_chart(prices, width=40, height=10):
    if len(prices) < 2:
        return "数据不足，无法生成图表"

    recent = prices[-width:]
    min_p = min(recent)
    max_p = max(recent)
    range_p = max_p - min_p if max_p != min_p else 1

    chart_lines = []
    for row in range(height, 0, -1):
        threshold = min_p + (range_p * row / height)
        line = ""
        for price in recent:
            if price >= threshold:
                line += "#"
            else:
                line += " "
        chart_lines.append(f"${max_p - range_p * (height - row) / height:8.1f} | {line}")

    return "\n".join(chart_lines)

def send_daily_summary(symbol_key, today_data, daily_data):
    symbol_cfg = config.symbols.get(symbol_key, {})
    symbol_name = symbol_cfg.get("name", symbol_key)
    unit = symbol_cfg.get("unit", "")

    change = today_data["close"] - today_data["open"]
    change_pct = (change / today_data["open"]) * 100

    if change > 0:
        direction = "上涨"
    elif change < 0:
        direction = "下跌"
    else:
        direction = "持平"

    prediction = predict_tomorrow(daily_data, symbol_name)

    content = "\n".join([
        f"品种: {symbol_name} ({unit})",
        f"日期: {today_data['date']}",
        f"开盘价: ${today_data['open']:.2f}",
        f"收盘价: ${today_data['close']:.2f}",
        f"最高价: ${today_data['high']:.2f}",
        f"最低价: ${today_data['low']:.2f}",
        f"当日{direction}: {change:+.2f} ({change_pct:+.2f}%)",
        f"波动幅度: ${today_data['high'] - today_data['low']:.2f}",
        f"",
        f"========== 明日预测 ==========",
        prediction,
        f"",
        f"========== 预测准确率 ==========",
        get_prediction_accuracy()
    ])

    send_feishu(f"{symbol_name}日报 - {today_data['date']} {direction}", content)
    # 修复：安全解析预测文本，避免 IndexError
    try:
        pred_first_line = prediction.split('\n')[0]
        if ': ' in pred_first_line:
            pred_direction = pred_first_line.split(': ')[1]
        else:
            pred_direction = "未知"
    except Exception:
        pred_direction = "解析失败"
    save_prediction(symbol_key, today_data['date'], pred_direction, today_data['close'], symbol_cfg.get("base_price", 0))

def get_volatility_multiplier():
    now_hour = int(time.strftime('%H'))
    periods = config.time_periods
    if not periods:
        return 1.0

    day_cfg = periods.get("day", {})
    night_cfg = periods.get("night", {})

    day_start = day_cfg.get("start", 8)
    day_end = day_cfg.get("end", 22)

    if day_start <= now_hour < day_end:
        return day_cfg.get("volatility_multiplier", 1.0)
    else:
        return night_cfg.get("volatility_multiplier", 1.5)

def is_weekend():
    weekday = datetime.now().weekday()
    return weekday >= 5

def monitor_symbol(symbol_key):
    symbol_cfg = config.symbols.get(symbol_key)
    if not symbol_cfg:
        logger.error(f"Symbol {symbol_key} not found in config")
        return

    symbol_name = symbol_cfg.get("name", symbol_key)
    unit = symbol_cfg.get("unit", "")
    base_price = symbol_cfg.get("base_price", 0)
    price_threshold = symbol_cfg.get("price_threshold", 0)
    volatility_threshold = symbol_cfg.get("volatility_threshold", 1.0)
    change_report_threshold = symbol_cfg.get("change_report_threshold", 0.1)

    price_history = []
    last_alert_time = 0
    last_reported_price = None
    high_price = 0
    low_price = float('inf')
    alert_cooldown = symbol_cfg.get("alert_cooldown", 300)  # 修复：改为可配置

    daily_data = load_daily_data(symbol_key)
    current_date = time.strftime('%Y-%m-%d')
    day_open_price = None
    day_close_price = None
    day_high = 0
    day_low = float('inf')
    last_summary_date = None

    if daily_data:
        last_summary_date = daily_data[-1].get("date")

    logger.info(f"=" * 50)
    logger.info(f"Monitor started: {symbol_name} ({unit})")
    logger.info(f"Base Price: {base_price}")
    logger.info(f"Alert Threshold: {price_threshold}")
    logger.info(f"Volatility Alert: +/-{volatility_threshold}%")
    logger.info(f"Change Report Threshold: +/-{change_report_threshold}%")
    logger.info(f"Check Interval: Every {config.check_interval} seconds")
    logger.info(f"Daily Summary: At 00:00")
    logger.info(f"History Days: {len(daily_data)}")
    logger.info(f"=" * 50)

    send_feishu(f"{symbol_name}监控系统", f"{symbol_name}({unit})实时监控已启动！\n每{config.check_interval//60}分钟检查一次价格，价格变化超过{change_report_threshold}%时发送状态报告。\n每天00:00发送日报及明日预测。")

    while True:
        try:
            if is_weekend() and not config.weekend_check:
                logger.info("Weekend detected, skipping check")
                time.sleep(60)
                continue

            current_price = get_price(symbol_key)
            if current_price is None:
                logger.warning("Failed to get price, retrying in 3 seconds...")
                time.sleep(3)
                continue

            price_history.append(current_price)
            if len(price_history) > 100:
                price_history.pop(0)

            if current_price > high_price:
                high_price = current_price
            if current_price < low_price:
                low_price = current_price

            if current_price > day_high:
                day_high = current_price
            if current_price < day_low:
                day_low = current_price

            if day_open_price is None:
                day_open_price = current_price

            day_close_price = current_price

            current_time = time.time()
            change_from_base = ((current_price - base_price) / base_price) * 100

            direction = "UP" if change_from_base > 0 else ("DOWN" if change_from_base < 0 else "FLAT")

            logger.info(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {symbol_name}: ${current_price:.2f} ({direction}) Base:{base_price} Change:{change_from_base:+.2f}% High:${high_price:.2f} Low:${low_price:.2f}")

            now_date = time.strftime('%Y-%m-%d')

            if now_date != current_date:
                # 修复：先保存日报数据，再重置日内统计，避免跨天边界数据失真
                if last_summary_date != current_date and day_open_price is not None:
                    # 用当前价格作为收盘价
                    day_close_price = current_price
                    today_record = {
                        "date": current_date,
                        "open": round(day_open_price, 2),
                        "close": round(day_close_price, 2),
                        "high": round(day_high, 2),
                        "low": round(day_low, 2)
                    }
                    daily_data.append(today_record)
                    if len(daily_data) > config.max_history_days:
                        daily_data = daily_data[-config.max_history_days:]
                    save_daily_data(symbol_key, daily_data)

                    send_daily_summary(symbol_key, today_record, daily_data)
                    last_summary_date = current_date
                    logger.info(f"Daily Summary Sent for {current_date}")

                # 重置日内统计
                current_date = now_date
                day_open_price = current_price
                day_close_price = current_price
                day_high = current_price
                day_low = current_price

            vol_multiplier = get_volatility_multiplier()
            adjusted_volatility_threshold = volatility_threshold * vol_multiplier

            should_alert = False
            alert_type = []

            # 修复：价格突破阈值支持双向预警（高于或低于）
            if price_threshold > 0:
                if current_price >= price_threshold:
                    should_alert = True
                    alert_type.append("价格突破上限阈值")
                elif current_price <= base_price * 2 - price_threshold:  # 对称阈值
                    should_alert = True
                    alert_type.append("价格跌破下限阈值")

            if len(price_history) >= 2:
                change_from_last = abs((current_price - price_history[-2]) / price_history[-2] * 100)
                if change_from_last >= adjusted_volatility_threshold:
                    should_alert = True
                    alert_type.append(f"波动过大({change_from_last:.2f}%)")

            if should_alert and (current_time - last_alert_time) > alert_cooldown:
                trend_analysis = analyze_trend(price_history, base_price)

                content = "\n".join([
                    f"品种: {symbol_name} ({unit})",
                    f"当前价格: ${current_price:.2f} ({direction})",
                    f"变化幅度: {change_from_base:+.2f}%",
                    f"最高价格: ${high_price:.2f}",
                    f"最低价格: ${low_price:.2f}",
                    f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"\n{trend_analysis}"
                ])

                send_feishu(f"{symbol_name}预警 - {', '.join(alert_type)}", content)
                last_alert_time = current_time
                last_reported_price = current_price
                logger.info(f"Alert Sent: {', '.join(alert_type)}")

            elif last_reported_price is not None:
                change_from_reported = abs((current_price - last_reported_price) / last_reported_price * 100)
                if change_from_reported >= change_report_threshold:
                    trend_analysis = analyze_trend(price_history, base_price)

                    content = "\n".join([
                        f"品种: {symbol_name} ({unit})",
                        f"当前价格: ${current_price:.2f} ({direction})",
                        f"变化幅度: {change_from_base:+.2f}%",
                        f"最高价格: ${high_price:.2f}",
                        f"最低价格: ${low_price:.2f}",
                        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                        f"\n{trend_analysis}"
                    ])

                    send_feishu(f"{symbol_name}状态报告", content)
                    last_reported_price = current_price
                    logger.info(f"Status Report Sent - Price Changed {change_from_reported:.2f}%")

            time.sleep(config.check_interval)

        except Exception as e:
            logger.error(f"Error: {str(e)}")
            time.sleep(5)

class MonitorHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html = self.generate_dashboard()
            self.wfile.write(html.encode('utf-8'))
        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "running", "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')}).encode())
        else:
            super().do_GET()

    def generate_dashboard(self):
        html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>黄金监控看板</title>
<style>
body { font-family: Arial, sans-serif; background: #1a1a2e; color: #eee; margin: 0; padding: 20px; }
h1 { color: #ffd700; text-align: center; }
.card { background: #16213e; border-radius: 10px; padding: 20px; margin: 10px; display: inline-block; min-width: 200px; }
.card h3 { color: #ffd700; margin: 0 0 10px 0; }
.price { font-size: 2em; font-weight: bold; }
.up { color: #00ff00; } .down { color: #ff4444; }
#update { text-align: center; color: #888; margin-top: 20px; }
</style></head><body>
<h1>黄金价格实时监控</h1>
<div id="dashboard"><p>加载中...</p></div>
<p id="update"></p>
<script>
function refresh() {
    fetch('/api/status').then(r=>r.json()).then(d=>{
        document.getElementById('update').textContent = '最后更新: ' + d.time;
    });
}
setInterval(refresh, 5000);
refresh();
</script></body></html>"""
        return html

def start_web_dashboard():
    if not config.web_dashboard.get("enabled", False):
        return
    port = config.web_dashboard.get("port", 8080)
    server = HTTPServer(('0.0.0.0', port), MonitorHandler)
    logger.info(f"Web dashboard started on port {port}")
    server.serve_forever()

def run_once():
    """单次运行模式：获取所有品种价格，发送早报后退出"""
    logger.info("单次运行模式启动")
    logger.info(f"Webhooks 配置: {len(config.webhooks)} 个")
    if not config.webhooks:
        logger.error("❌ 没有配置 webhook 地址！请检查 FEISHU_WEBHOOK 环境变量或 config.json")

    today = datetime.now().strftime('%Y-%m-%d')
    weekday = datetime.now().strftime('%A')
    results = []

    for symbol_key, symbol_cfg in config.symbols.items():
        symbol_name = symbol_cfg.get("name", symbol_key)
        unit = symbol_cfg.get("unit", "")
        base_price = symbol_cfg.get("base_price", 0)

        logger.info(f"正在获取 {symbol_name} 价格...")
        current_price = get_price(symbol_key)
        if current_price is None:
            logger.warning(f"❌ {symbol_name} 价格获取失败")
            results.append(f"❌ {symbol_name}: 获取价格失败")
            continue

        logger.info(f"✅ {symbol_name} 当前价格: ${current_price:.2f}")
        change_pct = ((current_price - base_price) / base_price * 100) if base_price else 0
        direction = "📈" if change_pct > 0 else ("📉" if change_pct < 0 else "➡️")

        # 加载历史数据进行趋势分析
        daily_data = load_daily_data(symbol_key)
        prices = [d["close"] for d in daily_data[-7:]] if daily_data else []
        prices.append(current_price)
        trend = analyze_trend(prices, base_price) if len(prices) >= 2 else "数据不足"

        line = f"{direction} {symbol_name} ({unit})\n当前价格: ${current_price:.2f}\n{trend}"
        results.append(line)

        # 保存今日数据
        if daily_data:
            daily_data.append({
                "date": today,
                "open": current_price,
                "close": current_price,
                "high": current_price,
                "low": current_price
            })
            if len(daily_data) > config.max_history_days:
                daily_data = daily_data[-config.max_history_days:]
            save_daily_data(symbol_key, daily_data)

    # 获取国内金价
    domestic_cfg = config.domestic_gold
    if domestic_cfg.get("enabled", True):
        logger.info("正在获取国内金价...")
        domestic_price, domestic_source = get_domestic_price()
        if domestic_price:
            domestic_name = domestic_cfg.get("name", "国内黄金")
            domestic_unit = domestic_cfg.get("unit", "元/克")
            results.append(f"📊 {domestic_name} ({domestic_unit})\n当前价格: ¥{domestic_price:.2f}\n数据来源: {domestic_source}")
        else:
            results.append("❌ 国内黄金: 获取价格失败")

    # 获取汇率
    logger.info("正在获取美元/人民币汇率...")
    usdcny_rate = get_usdcny_rate()
    if usdcny_rate:
        results.append(f"💱 汇率参考\n美元/人民币: {usdcny_rate:.4f}")
    else:
        results.append("❌ 汇率: 获取失败")

    if results:
        header = f"☀️ 早安行情速报\n📅 {today} {weekday}\n{'='*30}"
        content = header + "\n\n" + "\n\n".join(results)
        logger.info(f"准备发送早报，webhooks: {config.webhooks}")
        success = send_feishu("每日行情早报", content)
        if success:
            logger.info("✅ 早报发送成功")
        else:
            logger.error("❌ 早报发送失败，请检查 webhook 地址是否有效")
    else:
        logger.warning("无可用数据")

def main():
    # 支持 --once 参数：单次运行模式（适用于 GitHub Actions 定时任务）
    if "--once" in sys.argv:
        logger.info("Gold Monitor - 单次运行模式")
        run_once()
        return

    logger.info("Gold Monitor System Starting...")
    logger.info(f"Symbols: {', '.join(config.symbols.keys())}")
    logger.info(f"Webhooks: {len(config.webhooks)} configured")

    if config.web_dashboard.get("enabled", False):
        dashboard_thread = threading.Thread(target=start_web_dashboard, daemon=True)
        dashboard_thread.start()

    threads = []
    for symbol_key in config.symbols:
        t = threading.Thread(target=monitor_symbol, args=(symbol_key,), daemon=True)
        t.start()
        threads.append(t)
        logger.info(f"Started monitor for {symbol_key}")

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        logger.info("Shutting down...")

if __name__ == "__main__":
    main()