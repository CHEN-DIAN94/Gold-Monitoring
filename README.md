# 黄金价格监控系统

多品种贵金属价格监控平台，通过企业微信机器人推送每日行情早报。

## 功能

- **多品种监控** - 黄金、白银、原油
- **多数据源容灾** - 新浪财经、Metals Live、ExchangeRate API 自动切换
- **每日早报** - 通过企业微信推送价格和趋势分析
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

利用 GitHub Actions 每天早上8点自动发送行情早报，无需本地电脑运行。

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

完成！每天早上8点（北京时间）会自动发送行情早报到企业微信。

## 运行模式

| 模式 | 命令 | 说明 |
|------|------|------|
| 持续监控 | `python 黄金监控.py` | 每5分钟检查价格，异常时预警 |
| 单次运行 | `python 黄金监控.py --once` | 获取一次价格后退出 |
| 守护进程 | 双击 `start_daemon.bat` | 崩溃自动重启 |

## 配置说明

### 监控品种

| 品种 | 代码 | 说明 |
|------|------|------|
| 黄金 | hf_GC | 国际现货黄金 |
| 白银 | hf_SI | 国际现货白银 |
| 原油 | hf_CL | 国际原油期货 |

### 参数调整

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `base_price` | 4720 | 基准价格 |
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

## 数据源

| 优先级 | 数据源 | 说明 |
|--------|--------|------|
| 1 | 新浪财经 | 主要数据源 |
| 2 | Metals Live API | 备用 |
| 3 | ExchangeRate API | 最后备用 |
