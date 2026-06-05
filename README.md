# 黄金价格监控系统 v2.0

黄金价格监控平台，通过飞书机器人推送每日行情早报，支持国际金价 + 国内金价 + 实时汇率。

## 功能

- **国际金价监控** - 美元/盎司实时追踪
- **国内金价监控** - 人民币/克，多数据源自动切换
- **实时汇率** - 美元/人民币汇率参考
- **多数据源容灾** - 每个维度多个数据源，自动故障转移
- **每日早报** - 通过飞书推送价格和趋势分析
- **本地监控** - 持续运行模式，价格异常时实时预警

## 快速开始

### 1. 配置

编辑 `config.json`，填入你的飞书 webhook：

```json
{
  "webhooks": ["https://open.feishu.cn/open-apis/bot/v2/hook/你的token"]
}
```

### 2. 本地运行

```bash
pip install requests

# 持续监控模式
python 黄金监控.py

# 单次运行模式（获取价格后退出）
python 黄金监控.py --once
```

### 3. GitHub Actions 自动早报（推荐）

利用 GitHub Actions 每天早上自动发送行情早报，无需本地电脑运行。

**第一步：上传代码到 GitHub**

```bash
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/money.git
git push -u origin main
```

**第二步：配置 Secrets**

在 GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret：

| 名称 | 值 |
|------|-----|
| `FEISHU_WEBHOOK` | 你的飞书机器人 webhook URL |

**第三步：启用 Actions**

进入仓库 Actions 页面，点击 "I understand my workflows, go ahead and enable them"。

完成！每天早上会自动发送行情早报到飞书（因 GitHub Actions 有延迟，实际触发时间为北京时间凌晨4点左右，确保8点前送达）。

## 早报示例

```
☀️ 早安行情速报
📅 2026-06-05 Thursday
==============================

📈 黄金 (美元/盎司)
当前价格: $4470.76
当前趋势: 温和上涨
预测: 市场情绪偏多，上方压力位在4515.47附近

📊 国内黄金 (元/克)
当前价格: ¥973.75
数据来源: 国际价换算

💱 汇率参考
美元/人民币: 6.7745
```

## 运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| 持续监控 | `python 黄金监控.py` | 每5分钟检查价格，异常时预警 |
| 单次运行 | `python 黄金监控.py --once` | 获取一次价格后退出 |
| 守护进程 | 双击 `start_daemon.bat` | 崩溃自动重启 |

## 数据源

### 国际金价（美元/盎司）

| 优先级 | 数据源 | 说明 |
|--------|--------|------|
| 1 | 新浪财经 | 主数据源 |
| 2 | Metals Live API | 备用 |
| 3 | ExchangeRate API | 兜底 |

### 国内金价（元/克）

| 优先级 | 数据源 | 说明 |
|--------|--------|------|
| 1 | 新浪财经 沪金主力 | 直接数据源 |
| 2 | 东方财富 Au9999 | 直接数据源 |
| 3 | 国际金价 × 汇率换算 | 兜底方案 |

### 汇率（USD/CNY）

| 优先级 | 数据源 | 说明 |
|--------|--------|------|
| 1 | 新浪财经 | 实时汇率 |
| 2 | Frankfurter API | 免费无需 key |

## 配置说明

### 参数调整

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `price_threshold` | 4720 | 预警阈值 |
| `volatility_threshold` | 1.0 | 波动预警百分比 |
| `check_interval` | 300 | 检查间隔（秒） |
| `weekend_check` | false | 是否周末监控 |

## 文件结构

```
money/
├── 黄金监控.py              # 主程序
├── config.json              # 配置文件
├── start_daemon.bat         # 守护进程脚本
├── .github/workflows/
│   ├── ci.yml               # 代码验证
│   └── daily.yml            # 每日定时早报
├── information/             # 邮件监控服务
└── README.md
```
