# 地质勘探数据管理平台

面向地质勘探的钻孔编录、岩心取样、物探数据、化探分析、测绘资料与储量估算的综合数据管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 钻孔编录 | `borehole` | 钻孔 | 钻孔编号、勘探区、孔口坐标 |
| 岩心管理 | `core` | 岩心样本 | 岩心编号、所属钻孔、取样深度起 |
| 地层划分 | `stratigraphy` | 地层单元 | 单元编号、钻孔编号、地层名称 |
| 地球物理 | `geophysics` | 物探测线 | 测线编号、勘探区、物探方法 |
| 化探分析 | `geochem` | 化探样品 | 样品编号、样品类型、采样点位 |
| 化验数据 | `assay` | 化验结果 | 化验编号、样品编号、元素名称 |
| 地质填图 | `mapping` | 填图单元 | 图幅编号、图幅名称、比例尺 |
| 测绘控制 | `survey_point` | 控制点 | 点号、点类型、坐标X |
| 钻探日志 | `drilling_log` | 钻探记录 | 日志编号、钻孔编号、钻进深度 |
| 储量估算 | `reserve` | 矿体块段 | 块段编号、矿体名称、面积 |
| 样品登记 | `sample_registry` | 送检样品 | 送检编号、样品名称、采样位置 |
| 勘探设备 | `equipment` | 勘探仪器 | 仪器编号、仪器名称、型号规格 |
| 水文地质 | `hydro` | 水文观测点 | 观测编号、观测类型、所在钻孔 |
| 剖面编录 | `section` | 实测剖面 | 剖面编号、剖面名称、剖面长度 |
| 地质报告 | `geological_report` | 勘探报告 | 报告编号、勘探区、报告类型 |
| 遥感解译 | `remote` | 遥感数据 | 数据编号、数据源、分辨率 |
| 矿产评价 | `mineral` | 矿化线索 | 线索编号、勘探区、矿种 |
| 环境地质 | `environmental` | 环境调查点 | 调查编号、调查区域、灾害类型 |
| 禁入面工作台 | `workbench` | 只读访问面 / 现场会话 | 调查区域、访问面顶点、地图版本 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 地图禁入面联动工作台

环境地质的调查点改为由「只读访问面」联动工作台（前端入口：禁入面工作台；接口前缀 `/api/workbench`）。

口径要点：

- **圈面即只读面**：圈定调查区域生成多边形访问面（几何判定见 `app/geometry.py`，射线法点在面内）。
  人员会话按 `full` 或单个调查区域授权；现场记录只在授权面内可读，面外取数、跨面取记录一律 `403`。
- **跨面引用脱敏**：跨面引用图件只返回脱敏摘要（遮蔽原始图件、坐标底图、涉密备注、数据源路径），
  索取全量明细 `403`；面内引用可看全量。
- **同一地图版本联动**：全局维护单调递增 `map_version`，授权面变化（登记/改面/关入口/回收）即升版，
  灾害点图、调查台账、报告章节在会话 bundle 里按同一版本载入；旧版本提交返回 `409`，需先 `reload`。
- **历史报告快照**：报告章节定稿时固化「可见性快照」，此后不随授权面变化改变可见性；草稿章节实时联动。
- **撤销两段式**：先 `POST /surfaces/{id}/close-entry` 关闭图面入口（旧会话立即不能再提交），
  再 `POST /surfaces/{id}/reclaim-fields` 回收现场字段；未关入口直接回收会被拒绝。
- **并发改面**：`PUT /surfaces/{id}` 带 `base_version` 乐观锁、审签人与 `change_token`。
  基线过期返回 `409` 且整体回滚（旧会话权限不变）；同一 token 断线重连原样重放、不重复升版。
- **存量回填**：启动时与 `POST /backfill` 都会把存量环境调查点按「调查区域 + 几何归属」回填，幂等可重复执行。

> 注：仓库自带的 `backend/.venv` 与 `frontend/node_modules` 是在其他平台构建的，
> 本机若缺少原生依赖（如 `@rollup/rollup-linux-arm64-gnu`、`@esbuild/linux-arm64`），
> 重新执行 `make install` 即可；后端在无 pip 的精简镜像上需先 `get-pip.py` 引导。
