# MaiBot 微信个人号适配器

基于微信 iLink Bot API 的 MaiBot 适配器，使用 maim_message 通信协议。

## 功能特性

- 支持微信个人号扫码登录
- 支持文本、图片、视频、文件消息收发
- 支持 CDN 加密媒体传输
- 兼容 maim_message 协议，无缝对接 MaiBot

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

或者使用 pip 安装：

```bash
pip install maim_message loguru aiohttp pycryptodome qrcode tomli-w
```

### 2. 配置

复制配置模板：

```bash
cp template/template_config.toml config.toml
```

编辑 `config.toml`，配置 MaiBot 连接信息：

```toml
[maibot_server]
enable_api_server = true
base_url = "ws://127.0.0.1:8080/ws"
api_key = ""
platform_name = "wechat"
```

### 3. 运行

```bash
python main.py
```

首次运行时会生成二维码链接，使用手机微信扫码登录。

## 配置说明

### MaiBot 服务器配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `enable_api_server` | 是否启用 API-Server 模式 | `true` |
| `base_url` | MaiBot WebSocket 地址 | `ws://127.0.0.1:8080/ws` |
| `api_key` | API 密钥 | `""` |
| `platform_name` | 平台标识 | `wechat` |

### 微信配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `base_url` | 微信 API 地址 | `https://ilinkai.weixin.qq.com` |
| `token` | 登录令牌 (自动获取) | `""` |
| `qr_poll_interval` | 二维码轮询间隔(秒) | `1` |
| `long_poll_timeout_ms` | 消息拉取超时(毫秒) | `35000` |

### 聊天控制

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `private_list_type` | 私聊名单类型 | `none` |
| `private_list` | 私聊白名单/黑名单 | `[]` |
| `ban_user_id` | 全局黑名单 | `[]` |

## 架构说明

```
微信用户 → iLink Bot API → [WeChat Adapter] → maim_message → MaiBot
                                    ↑
                            消息格式转换
```

### 目录结构

```
MaiBot-WeChat-Adapter/
├── main.py                 # 主入口
├── src/
│   ├── config/            # 配置管理
│   ├── logger.py          # 日志系统
│   ├── weixin_client.py   # 微信 API 客户端
│   ├── mmc_com_layer.py   # maim_message 通信层
│   ├── recv_handler/      # 消息接收处理
│   └── send_handler/      # 消息发送处理
├── template/              # 配置模板
├── requirements.txt       # 依赖列表
└── pyproject.toml         # 项目配置
```

## 注意事项

1. **微信个人号限制**：微信 iLink Bot API 仅支持私聊消息，不支持群聊
2. **登录有效期**：token 可能会过期，需要重新扫码登录
3. **媒体文件**：图片、视频等媒体文件通过微信 CDN 加密传输

## 许可证

MIT License
