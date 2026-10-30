# EPD E-Paper Wireless Gateway (`epd_gateway`)
### 4.2寸三色墨水屏无线网关 · Home Assistant 独立集成插件

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/v/release/eastwoodnet/epd-gateway-ha?include_prereleases)](https://github.com/eastwoodnet/epd-gateway-ha/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Validate](https://github.com/eastwoodnet/epd-gateway-ha/actions/workflows/validate.yaml/badge.svg)](https://github.com/eastwoodnet/epd-gateway-ha/actions/workflows/validate.yaml)

**EPD 墨水屏无线网关 (`epd_gateway`)** 是专为 **ESP32 + 4.2寸三色 (黑白红 400×300) 蓝牙墨水屏** 打造的 Home Assistant 深度集成。

无需额外部署任何独立的 Python/Docker 服务器，直接在 Home Assistant 内即可获得完整的：
- 📰 **报刊风 1X 原生点阵天气早报**（点阵锐化、可联动 HA 室内温湿度传感器）
- 📅 **今日日程看板**（支持 Google Calendar/Apple/Outlook iCal 订阅，或直接绑定 HA 日历实体）
- 🖼️ **3卡槽三色抖动相册工作台**（内置 Atkinson/Floyd-Steinberg 抖动算法与红色印章）
- 🕒 **24小时可视化排程甘特图**（智能子时段优先排序，按时自动切换天气、日程、相册与硬件万年历）
- 📌 **全端打通的即时便签系统**（HA `notify` 原生实体 + 服务调用 + iPhone 快捷指令 GET/POST 推送秒级刷屏）

---

## 📸 界面与画面展示

| 报刊风天气早报 (可融合室内温湿度) | 今日日程看板 (进行中红框高亮) | 侧边栏相册与24H排程工作台 |
| :---: | :---: | :---: |
| 400×300 锐利点阵 | 400×300 结构化日程 | 独立 WebUI 嵌于 HA 侧边栏 |

---

## 🛠️ 安装方法

### 推荐方式：通过 HACS 安装

#### 1. 添加自定义仓库
1. 打开 Home Assistant，点击左侧边栏的 **HACS**。
2. 点击右上角菜单（三个点） -> 选择 **自定义存储库 (Custom repositories)**。
3. 在弹窗中输入本仓库地址：`https://github.com/eastwoodnet/epd-gateway-ha`
4. 类别 (Type) 选择 **集成 (Integration)**，点击 **添加**。

#### 2. 下载并安装
1. 在 HACS 列表中搜索 **EPD 墨水屏无线网关**。
2. 点击右下角 **下载 (Download)**。
3. 下载完成后，根据提示 **重启 Home Assistant**。

---

### 方式二：手动安装 (Manual Install)
1. 从 [Releases 页面](https://github.com/eastwoodnet/epd-gateway-ha/releases) 下载最新的 `epd_gateway.zip` 或源码包。
2. 解压并将 `custom_components/epd_gateway` 目录完整拷贝至您的 Home Assistant 配置目录中的 `custom_components/` 下：
   ```text
   /config/custom_components/epd_gateway/
   ```
3. 重启 Home Assistant。

---

## 🔌 ESP32-C3 硬件网关刷机与配网指南

ESP32-C3 作为墨水屏的无线中继，负责通过 WiFi 从 Home Assistant 拉取渲染好的点阵数据并经由蓝牙低功耗 (BLE) 刷入墨水屏。

### 1. 固件烧录 (Flashing)
硬件使用标准 ESP32-C3 开发板（带 USB 接口），可通过以下任一方式烧录固件：
- **方式 A (推荐)：PlatformIO 一键编译烧录**
  ```bash
  cd esp32-gateway
  pio run -t upload
  ```
- **方式 B：esptool.py 命令行烧录预编译固件**
  ```bash
  esptool.py --chip esp32c3 --port /dev/ttyUSB0 write_flash 0x0 firmware.bin
  ```

---

### 2. 首次上电 AP 热点配网 (Captive Portal)
1. 固件刷入后首次通电（或在 WiFi 连接超时、长按板载 Boot / IO9 按钮 3 秒后），ESP32 会自动启动 AP 配网热点：
   - **WiFi 热点名 (SSID)**：`EPD-Gateway-XXXX`（XXXX 为开发板 MAC 地址后 4 位）
   - **默认热点密码**：`12345678`
   - **配网管理 IP**：`192.168.4.1`
2. 用手机或电脑搜索并连接该 WiFi 热点，在浏览器中打开：
   ```text
   http://192.168.4.1
   ```
3. 在 Web 配置界面中完成两项设定：
   - **WiFi 设置**：填入家庭 2.4G WiFi 的 SSID 与密码。
   - **网关配置**：将「图片拉取 URL」设置为您的 Home Assistant 地址：
     ```text
     http://<HomeAssistant_IP>:8123/api/epd_gateway/screen.bin
     ```
4. 点击「保存并连接」，ESP32 将自动重启并连接到您的家庭局域网。

---

### 3. 串口命令行配置备用通道
如果您通过 USB 数据线连接着电脑终端（波特率 `115200`），也可以直接通过串口控制台免热点交互配置：
```text
wifi <SSID> <PASSWORD>                                   # 配置并连接 WiFi
server http://<HomeAssistant_IP>:8123/api/epd_gateway/screen.bin  # 配置拉取 URL
status                                                   # 查看当前连接状态与 IP
reboot                                                   # 重启网关
```

---

## ⚙️ 配置说明 (Configuration)

### 步骤 1：添加集成与绑定网关
1. 进入 Home Assistant **设置 (Settings)** -> **设备与服务 (Devices & Services)** -> **添加集成**。
2. 搜索并选择 **EPD 墨水屏无线网关 (`epd_gateway`)**。
3. 在弹出对话框中配置以下参数（后续可随时在集成选项中修改）：
   - **ESP32 网关地址 (`gateway_url`)**：局域网内 ESP32 网关的 HTTP 地址，例如 `http://192.168.1.100`（用于有新排程或便签时主动发起即时唤醒）。
   - **关联 HA 天气实体 (`weather_entity`)** *(可选)*：例如 `weather.home`。若留空则自动按下方城市查询 `wttr.in`。
   - **关联 HA 室内温度传感器 (`indoor_temp_entity`)** *(可选)*：例如 `sensor.workroom_temperature`。绑定后天气界面的右侧第一行会自动显示真实的「室内温度」。
   - **关联 HA 室内湿度传感器 (`indoor_humidity_entity`)** *(可选)*：例如 `sensor.workroom_humidity`。绑定后天气界面的右侧第二行会自动显示真实的「室内湿度」。
   - **关联 HA 日历实体 (`calendar_entity`)** *(可选)*：例如 `calendar.personal`。当未配置 iCal 链接时自动从此实体读取今日日程。
   - **默认天气城市 (`weather_city`)** *(可选)*：如 `Tianjin` 或 `Shanghai`，若留空且未选天气实体则自动按公网 IP 定位。
   - **iCal 日历订阅链接 (`calendar_ical_url`)** *(可选)*：支持 Google Calendar、Apple iCloud、Outlook 或飞书的 `.ics` 共享链接（以 `https://` 或 `webcal://` 开头）。
   - **在左侧边栏注册工作台 (`register_panel`)**：默认勾选，将在 HA 侧边栏添加「EPD 墨水屏」快速入口。

---

### 步骤 2：配置 ESP32 硬件网关拉取地址
登录您的 ESP32 网关 Web 管理后台（或通过局域网 API），将图片拉取 URL 配置为 Home Assistant 的服务地址：
```text
http://<HomeAssistant_IP>:8123/api/epd_gateway/screen.bin
```
*(注：集成同时也兼容了短路径 `http://<HomeAssistant_IP>:8123/screen.bin`)*

> [!NOTE]
> 该接口专为 ESP32 客户端放行，无需传递 Bearer Token，支持标准 HTTP ETag。当排程未变或处于免打扰时直接响应 `304 Not Modified`，最大化延长墨水屏与网关寿命。

---

## 📱 功能使用说明

### 1. 左侧边栏「EPD 墨水屏」工作台
点击左侧边栏的 **EPD 墨水屏** 即可进入专属控制台：
- **相册工作台**：支持 3 个独立图片卡槽，支持上传任意格式图片、拖拽居中缩放、实时预览三色抖动效果、加盖防伪红色印章，并一键推送到对应卡槽。
- **24 小时排程甘特图**：以可视化时间轴管理全天不同时段的显示模式（早安天气、今日日程、相册轮播、硬件万年历、免打扰休眠），支持重叠冲突智能排序。
- **即时便签推送**：输入标题与备忘内容，设定保留时长（15~720分钟），一键插播覆盖当前画面。
- **网关联动测试**：提供「立即触发同步」和「切换硬件原生万年历 (0x20)」便捷调试按钮。

---

### 2. 即时便签推送通道 (三端打通)

本插件提供三种互通的即时便签推送方式，均写入同一队列并立即唤醒屏幕：

#### 方式 A：Home Assistant 原生通知实体 (`notify`)
在自动化或开发者工具 -> 动作 (Actions) 中直接调用：
```yaml
action: notify.send_message
target:
  entity_id: notify.epd_4_2cun_san_se_mo_shui_ping_wang_guan_mo_shui_ping_tong_zhi_tui_song_memo_notify
data:
  title: "🚪 门锁告警"
  message: "入户门开门超时未关，请检查！"
```

#### 方式 B：插件专属服务 (`epd_gateway.push_memo`)
```yaml
action: epd_gateway.push_memo
data:
  title: "📌 桌面备忘"
  text: "今晚记得去菜鸟驿站拿快递，取件码 5-2-108。"
  duration_min: 120
  sender: "家庭自动化"
```
如需提前撤回便签恢复常规排程，调用动作 `epd_gateway.clear_memo` 即可。

#### 方式 C：iPhone 快捷指令 / Bark 风格 URL 触发
在 iPhone「快捷指令」App 中添加「获取 URL 内容」，填写：
```text
GET http://<HomeAssistant_IP>:8123/api/epd_gateway/push?text=今晚开会&title=重要备忘&duration_min=60
```
或直接使用短链接：
```text
GET http://<HomeAssistant_IP>:8123/api/push?text=今晚开会
```
无论在手机桌面小组件或 Siri 语音触发，屏幕均可在秒级内同步刷新！

> [!TIP]
> **关于 8123 端口认证与安全调用说明：**
> 1. **局域网内 (LAN) 免认证直连**：
>    插件在 Home Assistant 视图注册层已显式声明 `requires_auth = False`，这意味着**在家庭局域网内，iPhone、脚本或第三方系统调用 `/api/epd_gateway/push` 与 `/api/push` 时，无需携带任何 Token 或认证凭据**，开箱即可调用。
> 2. **外网远程推送推荐方式（iOS Home Assistant App 原生动作）**：
>    若您身处外网（4G/5G），**最优雅、最安全的方式是不向公网暴露 8123 端口**。在 iPhone「快捷指令」中直接选用 Home Assistant 官方 App 提供的原生动作：
>    - 动作选择：`Home Assistant -> 调用服务 (Call Service)`
>    - 服务选择：`epd_gateway.push_memo`
>    - 参数填入：`{"title": "外网备忘", "text": "提醒回家买牛奶"}`
>    - 该方式完全经由 HA 官方的加密安全通道（Nabu Casa 或家庭反代）双向鉴权，安全无虞。
> 3. **外网 HTTP API 鉴权调用**：
>    若您通过第三方自动化平台或公网 HTTP 接口调用反代后的 HA，只需在请求 Header 中附加标准的 HA 长期访问令牌 (Long-Lived Access Token)：
>    ```text
>    Authorization: Bearer <YOUR_LONG_LIVED_ACCESS_TOKEN>
>    ```

---

### 3. Home Assistant 自动化联动范例 (Automations)

本集成完全契合 Home Assistant 2024.8+ / 2025.x 现代架构规范，支持可视化 UI 动作编辑器（表单带有完整中文提示与校验）及 YAML 语法，并提供现代 `NotifyEntity` 实体平台。

#### 范例 1：家庭安防告警即时插播 (基于 Notify 实体)
当门窗传感器开启超时或烟雾告警时，立即打断当前排程并在墨水屏上红框醒目显示：
```yaml
alias: "墨水屏：大门长时间未关告警"
trigger:
  - platform: state
    entity_id: binary_sensor.front_door
    to: "on"
    for:
      minutes: 5
action:
  - action: notify.send_message
    target:
      entity_id: notify.epd_4_2cun_san_se_mo_shui_ping_wang_guan_mo_shui_ping_tong_zhi_tui_song_memo_notify
    data:
      title: "🚪 门锁安全告警"
      message: "入户防盗门已开启超过 5 分钟，请及时确认关闭！"
```

#### 范例 2：早晨定时唤醒与下班日程提醒 (基于专属服务)
配合特定生活场景，通过服务调用自动切屏或推送重要备忘：
```yaml
alias: "墨水屏：晚上 22 点睡前提醒与日历预告"
trigger:
  - platform: time
    at: "22:00:00"
action:
  - action: epd_gateway.push_memo
    data:
      title: "🌙 晚安提醒"
      text: "记得关好厨房燃气阀门；明早 09:30 有团队周会。"
      duration_min: 480
      sender: "生活管家"
```

#### 范例 3：全天闲时兜底模式联动
根据家庭模式（离家/回家）动态调整墨水屏闲时状态：
```yaml
alias: "墨水屏：全员离家切换为万年历省电"
trigger:
  - platform: state
    entity_id: zone.home
    to: "0"
action:
  - action: epd_gateway.set_fallback_mode
    data:
      mode: "native_calendar"
```

---

### 4. 系统架构与版本兼容性保障

为了确保在 Home Assistant 频繁的版本迭代中长期稳定免维护，本插件在架构层面遵循了以下现代标准：
- **严格遵循非阻塞异步规范 (Async Event Loop Integrity)**：全面兼容 HA 2024.5+ 启用的主事件循环阻塞侦测机制。所有相册图片编码、抖动算法计算与字体加载均由 `hass.async_add_executor_job` 委托至后台线程池执行，绝不卡死系统主循环。
- **拥抱现代 `NotifyEntity` 实体规范**：放弃了已被 HA 官方计划逐步废弃的旧版 `notify.yaml` 机制，改用全新实体化模型，未来更新无缝衔接。
- **现代化 `action:` 语法与 UI 选择器**：在 `services.yaml` 中为所有服务参数定义了标准的 HA `selector`，在自动化编辑器的可视化 UI 中具备完善的输入提示、滑动条与单位展示。
- **自动化持续集成 (CI)**：代码仓库配置了官方 `hacs/action` 与 `home-assistant/actions/hassfest` 双重自动化校验，在每一次提交与发版时严格验证清单、本地化语言包及品牌规则。

---

### 5. Home Assistant 实体一览

集成加载后会在 Home Assistant 设备列表中创建设备 **EPD 4.2寸三色墨水屏网关**，包含以下实体：

| 实体类型 | 实体名称 | 说明 |
| :--- | :--- | :--- |
| `sensor` | 当前生效画面模式 (`active_mode`) | 显示当前墨水屏展示的模式（早安天气 / 日程看板 / 即时便签等），附带到期时间等属性 |
| `image` | 墨水屏实时画面预览 (`screen_preview`) | 在 HA 仪表盘中实时查看墨水屏当前 400×300 真实画面的渲染图 |
| `select` | 闲时兜底模式 (`fallback_mode`) | 自由切换全天无排程规则时的默认底模（万年历 / 相册 / 天气等） |
| `button` | 立即触发网关同步 (`sync_now`) | 手动通知 ESP32 立即拉取并刷屏 |
| `button` | 切换硬件原生万年历 (`native_calendar`) | 发送 0x20 BLE 指令切换墨水屏片上硬件万年历 |
| `button` | 撤回即时便签 (`clear_memo`) | 提前撤销插播便签并恢复日常排程 |
| `notify` | 墨水屏通知推送 (`memo_notify`) | 标准通知平台实体，无缝接入 HA 各类告警自动化 |

---

## ❓ 常见问题 (FAQ)

<details>
<summary><b>Q: 屏幕刷新时偶尔提示超时，但墨水屏其实已经变了？</b></summary>
这是由于墨水屏在高压全刷启动瞬间电荷泵电流波动导致蓝牙回执有微小延迟。集成已将触发超时放宽至 8 秒，若偶发提示无需担心，只要画面变了说明指令已经生效。
</details>

<details>
<summary><b>Q: 为什么天气界面不显示室内温度？</b></summary>
请在集成卡片的「配置/选项」中，绑定 <code>indoor_temp_entity</code>（如 <code>sensor.workroom_temperature</code>）。绑定后右侧列会自动从显示「体感温度」切换为显示「室内温度」。
</details>

<details>
<summary><b>Q: 支持多大尺寸的墨水屏？</b></summary>
当前版本核心排版针对 4.2寸三色黑白红墨水屏（400×300 分辨率）进行了报刊级 1X 手工点阵调优与字模对齐；后续版本将扩展更多屏幕尺寸。
</details>

---

## 📄 开源许可
本项目遵循 [MIT License](LICENSE) 开源协议。
