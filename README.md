# 甄选电商企业智能业务平台

这是按照《电商平台买家端运营端与 RAG 智能中台项目方案》落地的电商交易、客服与治理一体化参考实现。工单 1 作为退款/客诉主链，工单 5/6/8/10 分别以可审计 Trace、零信任安全、多级意图与异常兜底、语音控制面横切接入。

## 两个系统入口

- 平台门户：<http://127.0.0.1:18000/>
- 企业统一登录（买家/客服/运营角色路由）：<http://127.0.0.1:18000/login>
- 买家服务系统：<http://127.0.0.1:18000/buyer>
- 客服工作台：<http://127.0.0.1:18000/cs>
- 运营治理系统：<http://127.0.0.1:18000/ops>

演示账号：`buyer / buyer123`、`csr / csr123`、`manager / manager123`、`admin / admin123`。

## 已实现

- 买家端：商品浏览、分类/品牌/店铺/价格筛选、详情与 SKU 规格、收藏、会员资料、积分、优惠券领取与使用、地址簿、按店铺购物车勾选结算、运费/优惠/发票明细、下单支付、取消订单、物流轨迹、确认收货、订单详情时间线、商品评价、仅退款/退货退款/换货、逆向物流、工单、文本与语音客服。
- 商品中心：43 件商品、14 个典型电商类目、43 个不重复本地商品视觉；其中手机、平板、笔记本、耳机、手表、键鼠、音箱、游戏机等数码 SKU 使用本地真实摄影图，支持品牌/原价/标签/规格/评价数、库存、详情、改价和运营库存调整。
- 客服端：售后队列详情与批准/拒绝、工单回复/解决/转主管、订单上下文、RAG 检索与引用复制、语音客服。
- 运营端：经营看板（GMV、净收入、客单价、支付转化、退款率）、订单履约、商品发布/编辑/上下架、库存预占与流水、店铺管理、逆向物流验收、审计日志、知识运营、退赔决策、人工审批、CSV 批量审批、评测、安全、意图和 Telemetry。
- RAG：商品/物流/售后政策知识检索、来源引用、版本和租户字段；买家与客服咨询、售后决策、运营知识验证共用同一 ACL/版本/缺口链路。
- 售后决策：证据/OCR、欺诈、舆情并行 Agent；金额、风险、证据和 RAG 依据共同决定自动退款或 `SUSPENDED_HUMAN`，人工审批恢复后执行退款。
- 安全：Critic 注入/越狱/角色冒充检测、手机号/身份证/邮箱/银行卡/API Key 脱敏、Tool Policy 与临时 Bearer 令牌。
- 可观测：每次请求返回 trace_id，动态记录节点时延、Checkpoint、事件流、DLQ 和知识缺口。
- 语音适配：浏览器 ASR + TTS 播报与打断 + `/api/voice/turn` + `/ws/voice` 统一转写/意图/RAG/安全回合协议。
- RAG 深化：口语 Query 改写、混合词法重排、ACL/状态过滤、引用阈值、检索延迟和知识缺口记录。
- 部署：Docker Compose 配置（Web、Redis、PostgreSQL、前端）。

## 本地启动

要求 Python 3.11+。

```powershell
cd C:\Users\20380\Desktop\电商平台
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开 <http://127.0.0.1:18000>。API 文档：<http://127.0.0.1:18000/docs>。

## Docker 启动

```powershell
docker compose up --build -d
```

打开 <http://localhost:8080>。

## 测试

```powershell
pip install -r requirements-dev.txt
pytest -q
```

## 企业参考实现边界

当前默认使用内存数据和轻量混合词法 RAG，便于零配置演示。交易域已拆出 `app/commerce.py`；`/api/platform/capabilities` 与 `/api/ops/infrastructure` 会明确展示生产替换点。生产环境应将 `app/store.py` 替换为 PostgreSQL/pgvector 持久化，将 `app/rag.py` 替换为 Embedding + 向量库，将 `app/voice.py` 接入 WebRTC、VAD、流式 STT/TTS，将退款工具接入真实支付/退款网关、库存中心和物流平台，并启用 OIDC/RBAC、Redis Checkpointer/Streams 与 OpenTelemetry/Langfuse。

更详细的逐工单矩阵、重复功能清理记录和边界说明见 [`docs/工单融合实现审计.md`](docs/工单融合实现审计.md)。
