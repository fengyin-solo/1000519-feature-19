<template>
  <section class="page" data-module="workbench">
    <header class="page-head">
      <div>
        <h2>地图禁入面联动工作台</h2>
        <p class="page-desc">
          先圈定调查区域生成只读访问面：人员只在面内查看现场记录，跨面引用图件仅显示脱敏摘要，越权请求一律拒绝；
          授权面变化后灾害点图、调查台账与报告章节同步重载到同一地图版本。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="refreshOverview">刷新管理视图</button>
        <button class="btn" type="button" @click="runBackfill">存量点回填归属</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">当前地图版本</span>
        <strong class="stat-value">v{{ overview?.map_version ?? '-' }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">存量调查点（在面/面外）</span>
        <strong class="stat-value">
          {{ overview?.backfill.inside ?? '-' }} / {{ overview?.backfill.outside ?? '-' }}
        </strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">有效访问面</span>
        <strong class="stat-value">{{ activeSurfaces.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">打开中的会话</span>
        <strong class="stat-value">{{ overview?.open_sessions.length ?? 0 }}</strong>
      </article>
    </div>

    <div class="tab-bar">
      <button class="tab" :class="{ on: tab === 'admin' }" type="button" @click="tab = 'admin'">禁入面管理</button>
      <button class="tab" :class="{ on: tab === 'field' }" type="button" @click="tab = 'field'">现场工作台</button>
    </div>

    <span v-if="message" class="ok-text">{{ message }}</span>
    <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>

    <!-- ===================== 管理端 ===================== -->
    <div v-if="tab === 'admin'">
      <div class="wb-grid">
        <div class="panel">
          <h3>调查区域与只读访问面</h3>
          <MapCanvas :surfaces="overview?.surfaces ?? []" :points="overview?.points ?? []" />
          <table class="data-table">
            <thead>
              <tr><th>区域</th><th>状态</th><th>面版本</th><th>审签人</th><th>地图版本</th><th>操作</th></tr>
            </thead>
            <tbody>
              <tr v-for="s in overview?.surfaces ?? []" :key="s.id">
                <td>{{ s.调查区域 }}</td>
                <td>
                  <span class="badge" :data-state="s.状态">{{ s.状态 }}</span>
                </td>
                <td>v{{ s.版本 }}</td>
                <td>{{ s.审签人 }}</td>
                <td>v{{ s.地图版本 }}</td>
                <td class="row-actions">
                  <button class="link" type="button" @click="startRevise(s)">改面审签</button>
                  <button
                    v-if="s.状态 === '有效'"
                    class="link danger" type="button"
                    @click="closeEntry(s)"
                  >关闭入口</button>
                  <button
                    v-if="s.状态 === '入口已关闭'"
                    class="link danger" type="button"
                    @click="reclaimFields(s)"
                  >回收现场字段</button>
                </td>
              </tr>
            </tbody>
          </table>

          <h3 style="margin-top:16px">圈定 / 改面（以最新审签版本为准）</h3>
          <div class="form-grid">
            <label><span>调查区域</span>
              <input v-model="surfaceForm.region" :disabled="!!surfaceForm.id" placeholder="如：北区" />
            </label>
            <label><span>审签人</span><input v-model="surfaceForm.approver" placeholder="审签人姓名" /></label>
            <label><span>基线地图版本</span>
              <input v-model.number="surfaceForm.base_version" type="number" style="width:110px" />
            </label>
            <label class="full"><span>访问面顶点 JSON（[[x,y],…]，坐标系 0-1000）</span>
              <textarea v-model="surfaceForm.polygonText" rows="3" />
            </label>
          </div>
          <div class="row-actions">
            <button v-if="!surfaceForm.id" class="btn primary" type="button" @click="submitCreate">生成只读访问面</button>
            <template v-else>
              <button class="btn primary" type="button" @click="submitRevise">提交改面审签</button>
              <button class="btn ghost" type="button" @click="resetSurfaceForm">取消改面</button>
            </template>
          </div>
        </div>

        <div class="panel">
          <h3>可跨面引用图件</h3>
          <table class="data-table">
            <thead><tr><th>编号</th><th>名称</th><th>区域</th><th>比例尺</th></tr></thead>
            <tbody>
              <tr v-for="f in overview?.figures ?? []" :key="f.id">
                <td>{{ f.图件编号 }}</td><td>{{ f.图件名称 }}</td><td>{{ f.调查区域 }}</td><td>{{ f.比例尺 }}</td>
              </tr>
            </tbody>
          </table>
          <p class="hint">跨面人员调用图件时，原始图件、坐标底图、涉密备注、数据源路径一律遮蔽，仅返回脱敏摘要；索取全量明细返回 403。</p>

          <h3 style="margin-top:16px">报告章节（历史报告维持定稿时可见性快照）</h3>
          <table class="data-table">
            <thead><tr><th>章节</th><th>区域</th><th>状态</th><th>版本</th><th>操作</th></tr></thead>
            <tbody>
              <tr v-for="ch in overview?.chapters ?? []" :key="ch.id">
                <td>{{ ch.章节编号 }}</td><td>{{ ch.调查区域 }}</td>
                <td><span class="badge" :data-state="ch.状态 === '已定稿' ? '已撤销' : '有效'">{{ ch.状态 }}</span></td>
                <td>v{{ ch.地图版本 }}</td><td></td>
              </tr>
            </tbody>
          </table>
          <div class="row-actions" style="margin-top:8px">
            <input v-model="chapterRegion" placeholder="为区域生成报告章节，如 东区" />
            <button class="btn" type="button" @click="createChapter">生成章节草稿</button>
          </div>
        </div>
      </div>
    </div>

    <!-- ===================== 现场端 ===================== -->
    <div v-if="tab === 'field'">
      <div class="panel">
        <h3>进入只读访问工作台</h3>
        <div class="form-grid">
          <label><span>人员</span><input v-model="sessionForm.operator" placeholder="调查人员姓名" /></label>
          <label><span>授权范围</span>
            <select v-model="sessionForm.scope">
              <option value="full">全区（值班管理员）</option>
              <option v-for="s in activeSurfaces" :key="s.id" :value="s.调查区域">{{ s.调查区域 }}（单区域只读）</option>
            </select>
          </label>
        </div>
        <div class="row-actions">
          <button class="btn primary" type="button" @click="openSession">进入工作台</button>
          <button class="btn" type="button" :disabled="!bundle" @click="reloadBundle">重新载入到最新地图版本</button>
        </div>
      </div>

      <div v-if="bundle" class="wb-grid">
        <div class="panel">
          <h3>
            灾害点图
            <span class="tag">载入版本 v{{ bundle.hazard_map.version }}</span>
          </h3>
          <MapCanvas
            :surfaces="bundle.surfaces"
            :points="bundle.hazard_map.points"
            :allowed="true"
          />
          <p v-if="!isSessionLive" class="error-text">
            {{ bundle.session.reject_reason || '会话已关闭' }}，旧会话返回工作台后不得继续提交。
          </p>

          <h3 style="margin-top:16px">调查台账（只读，共 {{ bundle.ledger.total }} 点）</h3>
          <table class="data-table">
            <thead><tr><th>编号</th><th>区域</th><th>灾害类型</th><th>危害等级</th><th>现场记录</th></tr></thead>
            <tbody>
              <tr v-for="row in bundle.ledger.items" :key="row.id">
                <td>{{ row.调查编号 }}</td><td>{{ row.调查区域 }}</td>
                <td>{{ row.灾害类型 }}</td><td>{{ row.危害等级 }}</td>
                <td><button class="link" type="button" @click="loadField(row.id)">查看现场记录</button></td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="panel">
          <h3>现场记录（仅授权面内）</h3>
          <div v-if="activePointId === null" class="hint">在左侧台账选择一个调查点，仅面内记录可读。</div>
          <template v-else>
            <div class="form-grid">
              <label class="full"><span>调查点 #{{ activePointId }} · 现场描述</span>
                <textarea v-model="noteForm.现场描述" rows="2" :disabled="!isSessionLive" />
              </label>
              <label class="full"><span>取样记录</span>
                <textarea v-model="noteForm.取样记录" rows="2" :disabled="!isSessionLive" />
              </label>
              <label class="full"><span>处置建议</span>
                <textarea v-model="noteForm.处置建议" rows="2" :disabled="!isSessionLive" />
              </label>
            </div>
            <button class="btn primary" type="button" :disabled="!isSessionLive" @click="submitNote">提交现场记录</button>
          </template>

          <h3 style="margin-top:16px">跨面引用图件</h3>
          <div class="row-actions">
            <select v-model.number="figureId">
              <option v-for="f in overview?.figures ?? []" :key="f.id" :value="f.id">
                {{ f.图件编号 }} · {{ f.调查区域 }}
              </option>
            </select>
            <button class="btn" type="button" @click="referenceFigure(false)">脱敏摘要</button>
            <button class="btn danger-outline" type="button" @click="referenceFigure(true)">索取全量明细</button>
          </div>
          <pre v-if="figureResult" class="json-box">{{ figureResult }}</pre>

          <h3 style="margin-top:16px">报告章节（同一地图版本联动）</h3>
          <div v-for="ch in bundle.chapters" :key="ch.id" class="chapter-card">
            <div>
              <strong>{{ ch.章节编号 }} · {{ ch.调查区域 }}</strong>
              <span class="tag">{{ ch.状态 }}</span>
              <span class="tag">当前载入 v{{ ch.地图版本 }}</span>
              <span v-if="ch.快照版本" class="tag snapshot">定稿快照 v{{ ch.快照版本 }}</span>
            </div>
            <div class="hint">可见调查点：{{ ch.可见调查点.map((p) => p.调查编号).join('、') || '无' }}</div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref } from 'vue'

import { request } from '@/api/client'

// 轻量 SVG 地图：画访问面多边形与灾害点，面外点置灰，避免引入地图重依赖。
const MapCanvas = defineComponent({
  name: 'MapCanvas',
  props: {
    surfaces: { type: Array as () => Surface[], default: () => [] },
    points: { type: Array as () => HazardPoint[], default: () => [] },
    allowed: { type: Boolean, default: false },
  },
  setup(props) {
    const toPoints = (polygon: number[][]) => polygon.map((p) => `${p[0]},${p[1]}`).join(' ')
    const stateColor: Record<string, string> = {
      有效: 'rgba(31,111,235,0.18)',
      入口已关闭: 'rgba(180,35,24,0.12)',
      已撤销: 'rgba(100,116,139,0.10)',
    }
    return () =>
      h('svg', { viewBox: '0 0 1000 1000', class: 'map-canvas' }, [
        ...props.surfaces.map((s) =>
          h('polygon', {
            key: `s-${s.id}`,
            points: toPoints(s.polygon),
            fill: stateColor[s.状态] ?? 'rgba(31,111,235,0.18)',
            stroke: s.状态 === '有效' ? '#1f6feb' : s.状态 === '入口已关闭' ? '#b42318' : '#94a3b8',
            'stroke-width': 3,
          }),
        ),
        ...props.surfaces.map((s) =>
          h('text', {
            key: `t-${s.id}`,
            x: s.polygon[0]?.[0] ?? 20,
            y: (s.polygon[0]?.[1] ?? 20) - 12,
            class: 'map-label',
          }, () => `${s.调查区域}·${s.状态}`),
        ),
        ...props.points
          .filter((p) => p.x !== null && p.y !== null)
          .map((p) =>
            h('circle', {
              key: `p-${p.id}`,
              cx: p.x as number,
              cy: p.y as number,
              r: 9,
              fill: p.面内可见 || !props.allowed ? '#1f6feb' : '#cbd5e1',
              stroke: '#fff',
              'stroke-width': 2,
            }),
          ),
      ])
  },
})

interface Surface {
  id: number
  调查区域: string
  polygon: number[][]
  状态: string
  版本: number
  审签人: string
  地图版本: number
}
interface HazardPoint {
  id: number
  调查编号: string
  灾害类型: string
  x: number | null
  y: number | null
  归属区域: string | null
  面内可见: boolean
}
interface LedgerRow {
  id: number
  调查编号: string
  调查区域: string
  灾害类型: string
  危害等级: string
  影响范围: string
  调查状态: string
}
interface ChapterView {
  id: number
  章节编号: string
  调查区域: string
  状态: string
  地图版本: number
  快照版本: number | null
  可见调查点: { id: number; 调查编号: string }[]
}
interface SessionInfo {
  id: string
  operator: string
  scope: string
  map_version: number
  entry_open: boolean
  closed: boolean
  reject_reason: string | null
}
interface Bundle {
  map_version: number
  session: SessionInfo
  surfaces: Surface[]
  hazard_map: { version: number; points: HazardPoint[] }
  ledger: { version: number; items: LedgerRow[]; total: number }
  chapters: ChapterView[]
}
interface Overview {
  map_version: number
  backfill: { total: number; inside: number; outside: number }
  surfaces: Surface[]
  figures: { id: number; 图件编号: string; 图件名称: string; 调查区域: string; 比例尺: string }[]
  points: HazardPoint[]
  chapters: { id: number; 章节编号: string; 调查区域: string; 状态: string; 地图版本: number }[]
  open_sessions: { id: string; operator: string; scope: string; map_version: number; entry_open: boolean; closed: boolean }[]
}

const API = '/api/workbench'

const tab = ref<'admin' | 'field'>('admin')
const overview = ref<Overview | null>(null)
const message = ref('')
const errorMessage = ref('')

const activeSurfaces = computed(() => (overview.value?.surfaces ?? []).filter((s) => s.状态 === '有效'))

const surfaceForm = ref<{ id: number | null; region: string; approver: string; base_version: number | null; polygonText: string }>({
  id: null,
  region: '',
  approver: '',
  base_version: null,
  polygonText: '',
})
const chapterRegion = ref('')

const sessionForm = ref({ operator: '', scope: 'full' })
const bundle = ref<Bundle | null>(null)
const activePointId = ref<number | null>(null)
const noteForm = ref({ 现场描述: '', 取样记录: '', 处置建议: '' })
const figureId = ref<number>(1)
const figureResult = ref('')

const isSessionLive = computed(
  () => !!bundle.value && bundle.value.session.entry_open && !bundle.value.session.closed,
)

function flash(text: string, ok = true) {
  message.value = ok ? text : ''
  errorMessage.value = ok ? '' : text
}

async function call(path: string, init?: RequestInit, silent = false) {
  const res = await request(path, init)
  let payload: any = null
  try {
    payload = await res.json()
  } catch {
    payload = null
  }
  if (!res.ok) {
    const detail = payload?.detail ?? `请求失败（${res.status}）`
    if (!silent) flash(detail, false)
    const err = new Error(detail) as Error & { status?: number }
    err.status = res.status
    throw err
  }
  return payload
}

async function refreshOverview() {
  overview.value = await call(`${API}/overview`, undefined, true)
}

async function runBackfill() {
  const res = await call(`${API}/backfill`, { method: 'POST' }).catch((e) => e)
  if (res instanceof Error) return
  flash(res.message)
  await refreshOverview()
}

function parsePolygon(): number[][] {
  try {
    const parsed = JSON.parse(surfaceForm.value.polygonText)
    if (!Array.isArray(parsed) || !parsed.every((p) => Array.isArray(p) && p.length >= 2)) {
      throw new Error('格式')
    }
    return parsed.map((p) => [Number(p[0]), Number(p[1])])
  } catch {
    flash('访问面顶点需为 [[x,y],…] 形式的 JSON，且至少 3 个点', false)
    throw new Error('bad polygon')
  }
}

async function submitCreate() {
  const polygon = parsePolygon()
  const res = await call(`${API}/surfaces`, {
    method: 'POST',
    body: JSON.stringify({ region: surfaceForm.value.region, approver: surfaceForm.value.approver, polygon }),
  }).catch((e) => e)
  if (res instanceof Error) return
  flash(res.message)
  resetSurfaceForm()
  await refreshOverview()
}

function startRevise(s: Surface) {
  surfaceForm.value = {
    id: s.id,
    region: s.调查区域,
    approver: '',
    base_version: overview.value?.map_version ?? s.地图版本,
    polygonText: JSON.stringify(s.polygon),
  }
  flash(`已载入「${s.调查区域}」当前面顶点，调整后用最新版本审签提交；断线可重放同一令牌。`)
}

function resetSurfaceForm() {
  surfaceForm.value = { id: null, region: '', approver: '', base_version: null, polygonText: '' }
}

async function submitRevise() {
  const polygon = parsePolygon()
  const token = `rev-${surfaceForm.value.id}-${surfaceForm.value.base_version}-${Date.now()}`
  const res = await call(`${API}/surfaces/${surfaceForm.value.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      polygon,
      approver: surfaceForm.value.approver,
      base_version: surfaceForm.value.base_version,
      change_token: token,
    }),
  }).catch((e) => e)
  if (res instanceof Error) return
  flash(`${res.message}（令牌 ${token}，断线重连可原样重传）`)
  resetSurfaceForm()
  await refreshOverview()
}

async function closeEntry(s: Surface) {
  const res = await call(`${API}/surfaces/${s.id}/close-entry`, { method: 'POST' }).catch((e) => e)
  if (res instanceof Error) return
  flash(res.message)
  await refreshOverview()
}

async function reclaimFields(s: Surface) {
  const res = await call(`${API}/surfaces/${s.id}/reclaim-fields`, { method: 'POST' }).catch((e) => e)
  if (res instanceof Error) return
  flash(res.message)
  await refreshOverview()
}

async function createChapter() {
  const res = await call(`${API}/chapters`, {
    method: 'POST',
    body: JSON.stringify({ region: chapterRegion.value }),
  }).catch((e) => e)
  if (res instanceof Error) return
  flash(res.message)
  chapterRegion.value = ''
  await refreshOverview()
}

async function openSession() {
  figureResult.value = ''
  const res = await call(`${API}/sessions`, {
    method: 'POST',
    body: JSON.stringify(sessionForm.value),
  }).catch((e) => e)
  if (res instanceof Error) {
    bundle.value = null
    return
  }
  flash(res.message)
  await loadBundle(res.session.id)
}

async function loadBundle(sessionId: string) {
  bundle.value = await call(`${API}/sessions/${sessionId}/bundle`, undefined, true)
  activePointId.value = null
}

async function reloadBundle() {
  if (!bundle.value) return
  const sid = bundle.value.session.id
  try {
    const reloaded = await call(`${API}/sessions/${sid}/reload`, { method: 'POST' }, true)
    bundle.value = reloaded
    flash(`已重新载入到地图版本 v${reloaded.map_version}，灾害点图/台账/章节同步刷新`)
    activePointId.value = null
  } catch {
    /* 错误已由调用处统一提示 */
  }
}

async function loadField(pointId: number) {
  if (!bundle.value) return
  activePointId.value = pointId
  figureResult.value = ''
  try {
    const note = await call(
      `${API}/sessions/${bundle.value.session.id}/points/${pointId}/field`,
      undefined,
      true,
    )
    noteForm.value = {
      现场描述: note.现场描述 ?? '',
      取样记录: note.取样记录 ?? '',
      处置建议: note.处置建议 ?? '',
    }
  } catch (e) {
    noteForm.value = { 现场描述: '', 取样记录: '', 处置建议: '' }
    flash((e as Error).message, false)
  }
}

async function submitNote() {
  if (!bundle.value || activePointId.value === null) return
  const res = await call(
    `${API}/sessions/${bundle.value.session.id}/points/${activePointId.value}/field`,
    {
      method: 'POST',
      body: JSON.stringify({ values: noteForm.value, map_version: bundle.value.map_version }),
    },
  ).catch((e) => e)
  if (res instanceof Error) return
  flash(res.message)
}

async function referenceFigure(detail: boolean) {
  if (!bundle.value) return
  try {
    const res = await call(
      `${API}/sessions/${bundle.value.session.id}/figures/${figureId.value}/reference`,
      { method: 'POST', body: JSON.stringify({ detail }) },
      true,
    )
    figureResult.value = JSON.stringify(res, null, 2)
  } catch (e) {
    figureResult.value = `越权请求已拒绝：${(e as Error).message}`
    flash((e as Error).message, false)
  }
}

onMounted(refreshOverview)
</script>

<style scoped>
.tab-bar { display: flex; gap: 8px; margin: 8px 0 12px; }
.tab { border: 1px solid var(--border); background: #fff; border-radius: 6px 6px 0 0; padding: 8px 16px; cursor: pointer; }
.tab.on { background: var(--brand); color: #fff; border-color: var(--brand); }
.wb-grid { display: grid; grid-template-columns: 1.35fr 1fr; gap: 12px; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; display: flex; align-items: center; gap: 8px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-bottom: 10px; }
.form-grid label span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 2px; }
.form-grid input, .form-grid select, .form-grid textarea, .row-actions input, .row-actions select {
  width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font-size: 13px;
}
.form-grid .full { grid-column: 1 / -1; }
.badge { padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #eaf1ff; color: #1f6feb; }
.badge[data-state='入口已关闭'] { background: #fdeceb; color: #b42318; }
.badge[data-state='已撤销'] { background: #eef2f7; color: #64748b; }
.link.danger { color: #b42318; }
.btn.danger-outline { border-color: #b42318; color: #b42318; }
.tag { font-size: 11px; background: #eef2f7; border-radius: 4px; padding: 1px 6px; color: var(--muted); }
.tag.snapshot { background: #ecfdf3; color: #067647; }
.hint { color: var(--muted); font-size: 12px; margin: 6px 0; }
.ok-text { color: #067647; font-size: 13px; display: block; margin-bottom: 8px; }
.json-box { background: #0f172a; color: #dbeafe; border-radius: 6px; padding: 8px; font-size: 12px; max-height: 200px; overflow: auto; white-space: pre-wrap; }
.chapter-card { border: 1px solid var(--border); border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.map-canvas { width: 100%; height: 320px; background: #f8fafc; border: 1px solid var(--border); border-radius: 6px; }
:deep(.map-label) { font-size: 22px; fill: #334155; font-weight: 600; }
</style>
