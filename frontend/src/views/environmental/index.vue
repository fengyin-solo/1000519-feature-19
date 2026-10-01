<template>
  <section class="page workbench" data-module="environmental">
    <header class="page-head">
      <div>
        <h2>地图禁入面联动工作台</h2>
        <p class="page-desc">
          先圈定调查区域生成只读访问面，人员仅可在面内查看现场记录；跨面引用图件只显示脱敏摘要，越权与提交请求一律拒绝。
          授权面审签变化后，灾害点图、调查台账、报告章节同步重载到同一地图版本；历史报告维持生成时的可见性快照。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openFaceDialog">圈定调查区域生成访问面</button>
      </div>
    </header>

    <p v-if="errorMessage" class="banner error">{{ errorMessage }}</p>
    <p v-if="infoMessage" class="banner info">{{ infoMessage }}</p>

    <!-- 左侧：授权面列表 -->
    <div class="wb-layout">
      <aside class="face-pane">
        <div class="pane-head">
          <strong>授权面（只读访问面）</strong>
          <button class="link" type="button" @click="loadFaces">刷新</button>
        </div>
        <article
          v-for="face in faces"
          :key="face.id"
          class="face-card"
          :class="{ active: currentFaceId === face.id, revoked: face.状态 === '已撤销' }"
        >
          <header>
            <strong>{{ face.name }}</strong>
            <span class="tag" :class="statusClass(face.状态)">{{ face.状态 }}</span>
          </header>
          <p class="face-meta">调查区域：{{ face.调查区域.join('、') || '—' }}</p>
          <p class="face-meta">有效版本：V{{ face.有效版本 }} · {{ face.地图版本 }} · {{ face.审签人 }}</p>
          <p class="face-meta">图面入口：{{ face.图面入口 }} ｜ 现场字段：{{ face.现场字段 }}</p>
          <p v-if="face.待审签草稿数" class="face-meta warn">待审签改面草稿：{{ face.待审签草稿数 }} 份</p>
          <div class="face-actions">
            <button class="btn small" type="button" :disabled="face.状态 === '已撤销'" @click="enterFace(face)">
              {{ currentFaceId === face.id ? '回到工作台' : '进入工作台' }}
            </button>
            <button class="btn small" type="button" :disabled="!faceMutable(face)" @click="openChangeDialog(face)">改面</button>
            <button class="btn small danger" type="button" :disabled="face.状态 === '已撤销'" @click="revokeFace(face)">撤销访问</button>
            <button class="btn small" type="button" @click="openReports(face)">历史报告</button>
          </div>
        </article>
        <p v-if="!faces.length" class="empty-inline">尚未圈定任何授权面</p>
      </aside>

      <!-- 右侧：工作台主区 -->
      <main class="map-pane">
        <div v-if="!activeFace" class="empty-state big">
          请在左侧选择一个有效授权面进入工作台；访问面为只读，面内只可查看现场记录。
        </div>

        <template v-else>
          <div class="map-toolbar">
            <div>
              <strong>{{ activeFace.name }}</strong>
              <span class="tag" :class="statusClass(activeFace.状态)">{{ activeFace.状态 }}</span>
            </div>
            <div class="toolbar-actions">
              <button class="btn small" type="button" @click="reloadMap">重载到同一地图版本</button>
              <button class="btn small" type="button" @click="submitAttempt">试提交（只读拦截演示）</button>
              <button class="btn small primary" type="button" @click="generateReport">生成报告快照</button>
              <button class="btn small" type="button" @click="exitWorkbench">退出</button>
            </div>
          </div>

          <div v-if="bundle" class="version-line">
            当前地图版本：<strong>{{ bundle.地图版本 }}</strong>（审签 V{{ bundle.审签版本 }}）
            ｜ 会话版本：V{{ sessionVersion }}
            <span v-if="sessionVersion !== bundle.审签版本" class="banner warn inline">
              授权面已更新，灾害点图 / 调查台账 / 报告章节需同步重载
            </span>
          </div>

          <section class="layer-grid">
            <article class="layer-card">
              <h3>灾害点图</h3>
              <ul class="point-list">
                <li v-for="point in bundle.灾害点图.点位" :key="point.id">
                  <button class="link" type="button" @click="openRecord(point.id)">{{ point.调查编号 }}</button>
                  <span>{{ point.灾害类型 }} · {{ point.危害等级 }} · {{ point.现场字段状态 }}</span>
                </li>
              </ul>
            </article>

            <article class="layer-card">
              <h3>调查台账（{{ bundle.地图版本 }}）</h3>
              <table class="data-table compact">
                <thead>
                  <tr><th>调查编号</th><th>调查区域</th><th>灾害类型</th><th>危害等级</th><th>调查人员</th></tr>
                </thead>
                <tbody>
                  <tr v-for="row in bundle.调查台账.记录" :key="row.id">
                    <td>{{ row.调查编号 }}</td>
                    <td>{{ row.调查区域 }}</td>
                    <td>{{ row.灾害类型 }}</td>
                    <td>{{ row.危害等级 }}</td>
                    <td>{{ row.调查人员 }}</td>
                  </tr>
                </tbody>
              </table>
            </article>

            <article class="layer-card">
              <h3>报告章节</h3>
              <ul class="chapter-list">
                <li v-for="chapter in bundle.报告章节" :key="chapter.章节">
                  {{ chapter.章节 }}（{{ chapter.点位数量 }} 点）— 版本 {{ chapter.地图版本 }}
                  <small>{{ chapter.调查点.join('、') }}</small>
                </li>
              </ul>
            </article>
          </section>

          <section class="figure-grid">
            <article class="layer-card">
              <h3>面内图件（原文可见）</h3>
              <ul class="figure-list">
                <li v-for="figure in bundle.面内图件" :key="figure.图幅编号">
                  {{ figure.图幅编号 }} · {{ figure.图幅名称 }} · {{ figure.比例尺 }}
                </li>
                <li v-if="!bundle.面内图件.length" class="muted">本面暂无面内图件</li>
              </ul>
            </article>
            <article class="layer-card masked">
              <h3>跨面引用图件 <span class="tag mask">仅脱敏摘要</span></h3>
              <ul class="figure-list">
                <li v-for="figure in bundle.跨面引用图件" :key="figure.图幅编号">
                  {{ figure.图幅编号 }} · {{ figure.图幅名称 }} · {{ figure.比例尺 }}
                  <small>归属：{{ figure.归属面 }}｜{{ figure.摘要 }}</small>
                </li>
                <li v-if="!bundle.跨面引用图件.length" class="muted">无跨面引用</li>
              </ul>
            </article>
          </section>
        </template>
      </main>
    </div>

    <!-- 圈面 / 改面 对话框 -->
    <div v-if="dialog.mode" class="modal-mask" @click.self="closeDialog">
      <div class="modal">
        <h3>{{ dialog.mode === 'create' ? '圈定调查区域生成只读访问面' : '授权面改面（需审签）' }}</h3>
        <label class="form-row" v-if="dialog.mode === 'create'">
          <span>授权面名称</span>
          <input v-model="dialog.name" placeholder="如：城东滑坡调查禁入面" />
        </label>
        <label class="form-row">
          <span>调查区域（每行一个）</span>
          <textarea v-model="dialog.areasText" rows="4" placeholder="环境地质样例1&#10;环境地质样例3"></textarea>
        </label>
        <p class="muted small">
          {{ dialog.mode === 'change'
            ? '提交后生成改面草稿，需再点「审签改面」才生效；并发改面以最新审签版本为准，旧基线草稿会被驳回。'
            : '存量环境调查点将按调查区域自动回填归属。' }}
        </p>
        <div v-if="dialog.draft" class="banner warn">
          草稿 #{{ dialog.draft.草稿号 }}（基于 V{{ dialog.draft.base_version }}）已生成，待审签。
        </div>
        <div class="modal-actions">
          <button v-if="dialog.mode === 'create'" class="btn primary" type="button" @click="submitCreateFace">生成访问面</button>
          <template v-else>
            <button class="btn" type="button" :disabled="!!dialog.draft" @click="submitPrepareChange">提交改面草稿</button>
            <button class="btn primary" type="button" :disabled="!dialog.draft" @click="submitSignChange">审签改面</button>
          </template>
          <button class="btn ghost" type="button" @click="closeDialog">关闭</button>
        </div>
      </div>
    </div>

    <!-- 单条现场记录 / 跨面脱敏摘要 -->
    <div v-if="recordDetail" class="modal-mask" @click.self="recordDetail = null">
      <div class="modal">
        <h3>现场记录 #{{ recordDetail.id }}</h3>
        <pre class="record-pre">{{ JSON.stringify(recordDetail, null, 2) }}</pre>
        <p v-if="recordDetail.摘要" class="banner warn">{{ recordDetail.摘要 }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="recordDetail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 历史报告快照 -->
    <div v-if="reportPanel" class="modal-mask wide" @click.self="reportPanel = null">
      <div class="modal">
        <h3>历史报告（维持各自可见性快照）</h3>
        <table v-if="reportPanel.历史报告.length" class="data-table compact">
          <thead>
            <tr><th>报告</th><th>地图版本</th><th>生成时间</th><th>快照口径</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="report in reportPanel.历史报告" :key="report.id">
              <td>#{{ report.id }} {{ report.授权面 }}</td>
              <td>{{ report.地图版本 }}</td>
              <td>{{ report.生成时间 }}</td>
              <td>{{ report.可见性快照.现场记录 }} / {{ report.可见性快照.跨面图件 }}</td>
              <td><button class="link" type="button" @click="openReport(report.id)">查看快照</button></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">该面暂无历史报告</p>
        <pre v-if="reportSnapshot" class="record-pre">{{ JSON.stringify(reportSnapshot, null, 2) }}</pre>
        <div class="modal-actions">
          <button class="btn" type="button" @click="reportPanel = null">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Face = Record<string, any>
const ENDPOINT = '/api/environmental/workbench'

const faces = ref<Face[]>([])
const currentFaceId = ref<number | null>(null)
const activeFace = ref<Face | null>(null)
const bundle = ref<any>(null)
const sessionVersion = ref(0)
const errorMessage = ref('')
const infoMessage = ref('')
const recordDetail = ref<any>(null)
const reportPanel = ref<any>(null)
const reportSnapshot = ref<any>(null)

const dialog = reactive<{
  mode: '' | 'create' | 'change'
  faceId: number | null
  name: string
  areasText: string
  draft: any
}>({ mode: '', faceId: null, name: '', areasText: '', draft: null })

let flashTimer: ReturnType<typeof setTimeout> | undefined
function flash(message: string, ok = false) {
  if (ok) {
    errorMessage.value = ''
    infoMessage.value = message
  } else {
    infoMessage.value = ''
    errorMessage.value = message
  }
  clearTimeout(flashTimer)
  flashTimer = setTimeout(() => {
    errorMessage.value = ''
    infoMessage.value = ''
  }, 5000)
}

async function call(path: string, init: RequestInit & { token?: string | null } = {}) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = init.token !== undefined ? init.token : sessionToken()
  if (token) headers['X-Session-Token'] = token
  const { token: _omit, ...rest } = init as any
  const response = await request(path, { ...rest, headers: { ...headers, ...(rest.headers || {}) } })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const detail = payload?.detail || `请求失败（${response.status}）`
    throw new Error(detail)
  }
  return payload
}

function tokenKey(faceId: number) {
  return `env-workbench-token:${faceId}`
}
function sessionToken(): string | null {
  if (currentFaceId.value === null) return null
  return window.sessionStorage.getItem(tokenKey(currentFaceId.value))
}
function saveToken(faceId: number, token: string) {
  window.sessionStorage.setItem(tokenKey(faceId), token)
}

function statusClass(status: string) {
  if (status === '已撤销') return 'revoked'
  if (status.includes('待审签') || status.includes('撤销中')) return 'warn'
  return 'active'
}
function faceMutable(face: Face) {
  return face.状态 !== '已撤销' && face.状态 !== '撤销中·入口已关闭'
}

async function loadFaces() {
  try {
    const data = await call(`${ENDPOINT}/faces`, { token: null })
    faces.value = data.items ?? []
    if (activeFace.value) {
      activeFace.value = faces.value.find((item) => item.id === currentFaceId.value) || activeFace.value
    }
  } catch (error) {
    flash(error instanceof Error ? error.message : '授权面列表读取失败')
  }
}

async function enterFace(face: Face) {
  currentFaceId.value = face.id
  try {
    let token = sessionToken()
    if (!token) {
      const opened = await call(`${ENDPOINT}/faces/${face.id}/sessions`, {
        method: 'POST',
        body: JSON.stringify({ operator: '值班调查员' }),
        token: null,
      })
      token = opened.session_token as string
      saveToken(face.id, token)
    }
    const status = await call(`${ENDPOINT}/faces/${face.id}/sessions/me`)
    activeFace.value = face
    if (!status.会话有效) {
      flash('该会话已随授权撤销失效，请在其他有效授权面进入工作台')
      bundle.value = null
      return
    }
    sessionVersion.value = status.有效版本
    await reloadMap()
  } catch (error) {
    flash(error instanceof Error ? error.message : '进入工作台失败')
  }
}

async function reloadMap() {
  if (currentFaceId.value === null) return
  try {
    bundle.value = await call(`${ENDPOINT}/faces/${currentFaceId.value}/map`)
    sessionVersion.value = bundle.value.审签版本
    await loadFaces()
  } catch (error) {
    bundle.value = null
    flash(error instanceof Error ? error.message : '地图重载失败')
  }
}

function exitWorkbench() {
  currentFaceId.value = null
  activeFace.value = null
  bundle.value = null
}

async function openRecord(recordId: number) {
  try {
    recordDetail.value = await call(
      `${ENDPOINT}/faces/${currentFaceId.value}/records/${recordId}`,
    )
  } catch (error) {
    flash(error instanceof Error ? error.message : '现场记录读取失败')
  }
}

async function submitAttempt() {
  try {
    await call(`${ENDPOINT}/faces/${currentFaceId.value}/records`, {
      method: 'POST',
      body: JSON.stringify({ values: { 现场补录: '越权尝试' } }),
    })
  } catch (error) {
    flash(`提交已被拒绝：${error instanceof Error ? error.message : '只读访问面禁止提交'}`)
  }
}

async function generateReport() {
  try {
    await call(`${ENDPOINT}/faces/${currentFaceId.value}/reports`, { method: 'POST' })
    flash('报告已生成并固化当前地图版本与可见性快照', true)
  } catch (error) {
    flash(error instanceof Error ? error.message : '报告生成失败')
  }
}

async function revokeFace(face: Face) {
  if (!window.confirm(`确认撤销「${face.name}」？将先关闭图面入口，再回收现场字段，旧会话立即失效。`)) return
  try {
    await call(`${ENDPOINT}/faces/${face.id}/revoke/begin`, {
      method: 'POST',
      body: JSON.stringify({}),
      token: null,
    })
    flash('图面入口已关闭，正在回收现场字段…', true)
    await call(`${ENDPOINT}/faces/${face.id}/revoke/complete`, {
      method: 'POST',
      body: JSON.stringify({}),
      token: null,
    })
    window.sessionStorage.removeItem(tokenKey(face.id))
    if (currentFaceId.value === face.id) exitWorkbench()
    await loadFaces()
    flash('现场字段已回收，旧会话全部作废', true)
  } catch (error) {
    flash(error instanceof Error ? error.message : '撤销失败')
  }
}

function openFaceDialog() {
  Object.assign(dialog, { mode: 'create', faceId: null, name: '', areasText: '', draft: null })
}
function openChangeDialog(face: Face) {
  Object.assign(dialog, {
    mode: 'change',
    faceId: face.id,
    name: face.name,
    areasText: face.调查区域.join('\n'),
    draft: null,
  })
}
function closeDialog() {
  dialog.mode = ''
  dialog.draft = null
}

function parseAreas() {
  return dialog.areasText.split('\n').map((item) => item.trim()).filter(Boolean)
}

async function submitCreateFace() {
  try {
    const created = await call(`${ENDPOINT}/faces`, {
      method: 'POST',
      body: JSON.stringify({
        name: dialog.name.trim(),
        areas: parseAreas(),
        operator: '值班管理员',
      }),
      token: null,
    })
    closeDialog()
    await loadFaces()
    flash(`访问面已生成，回填存量调查点：${(created.回填调查点 || []).join('、') || '无'}`, true)
  } catch (error) {
    flash(error instanceof Error ? error.message : '访问面生成失败')
  }
}

async function submitPrepareChange() {
  try {
    const prepared = await call(`${ENDPOINT}/faces/${dialog.faceId}/changes/prepare`, {
      method: 'POST',
      body: JSON.stringify({ areas: parseAreas(), operator: '值班管理员' }),
      token: null,
    })
    dialog.draft = prepared.草稿
    flash('改面草稿已生成，等待审签', true)
  } catch (error) {
    flash(error instanceof Error ? error.message : '改面草稿提交失败')
  }
}

async function submitSignChange() {
  try {
    await call(`${ENDPOINT}/faces/${dialog.faceId}/changes/sign`, {
      method: 'POST',
      body: JSON.stringify({ operator: '审签人', draft_no: dialog.draft.草稿号 }),
      token: null,
    })
    closeDialog()
    await loadFaces()
    if (currentFaceId.value === dialog.faceId) await reloadMap()
    flash('改面已审签，灾害点图、调查台账、报告章节同步重载到新地图版本', true)
  } catch (error) {
    flash(error instanceof Error ? error.message : '改面审签未通过')
  }
}

async function openReports(face: Face) {
  reportSnapshot.value = null
  try {
    // 历史报告维持可见性快照：需持有该面会话；若无则先开只读会话
    let token = window.sessionStorage.getItem(tokenKey(face.id))
    if (!token && face.状态 !== '已撤销') {
      const opened = await call(`${ENDPOINT}/faces/${face.id}/sessions`, {
        method: 'POST',
        body: JSON.stringify({ operator: '值班调查员' }),
        token: null,
      })
      token = opened.session_token as string
      saveToken(face.id, token)
    }
    if (!token) {
      flash('授权面已撤销且本地无会话，历史报告快照需由面内既有会话查看')
      return
    }
    currentFaceId.value = face.id
    reportPanel.value = await call(`${ENDPOINT}/faces/${face.id}/reports`)
  } catch (error) {
    flash(error instanceof Error ? error.message : '历史报告读取失败')
  }
}

async function openReport(reportId: number) {
  try {
    reportSnapshot.value = await call(
      `${ENDPOINT}/faces/${currentFaceId.value}/reports/${reportId}`,
    )
  } catch (error) {
    flash(error instanceof Error ? error.message : '报告快照读取失败')
  }
}

onMounted(loadFaces)
</script>

<style scoped>
.workbench .wb-layout { display: grid; grid-template-columns: 320px 1fr; gap: 14px; align-items: start; }
.face-pane, .map-pane { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
.pane-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.face-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-bottom: 10px; background: #fbfdff; }
.face-card.active { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(31, 111, 235, 0.12); }
.face-card.revoked { opacity: 0.62; background: #f6f7f9; }
.face-card header { display: flex; justify-content: space-between; align-items: center; }
.face-meta { font-size: 12px; color: var(--muted); margin: 4px 0; }
.face-meta.warn { color: #b45309; }
.face-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.btn.small { padding: 3px 8px; font-size: 12px; }
.btn.danger { color: #b42318; border-color: #f0b8b2; }
.tag { font-size: 11px; border-radius: 10px; padding: 1px 8px; background: #eef2f7; color: var(--muted); }
.tag.active { background: #e7f1ff; color: #1d4ed8; }
.tag.warn { background: #fef3c7; color: #b45309; }
.tag.revoked { background: #fee4e2; color: #b42318; }
.tag.mask { background: #f3e8ff; color: #7e22ce; }
.banner { border-radius: 6px; padding: 8px 10px; font-size: 13px; margin: 8px 0; }
.banner.error { background: #fee4e2; color: #b42318; }
.banner.warn { background: #fef3c7; color: #92400e; }
.banner.info { background: #e7f1ff; color: #1d4ed8; }
.banner.inline { display: inline-block; margin: 0 0 0 8px; padding: 2px 8px; }
.map-toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.toolbar-actions { display: flex; gap: 6px; }
.btn.primary { background: var(--brand); border-color: var(--brand); color: #fff; }
.version-line { font-size: 13px; color: var(--muted); margin-bottom: 10px; }
.layer-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.layer-grid .layer-card:first-child { grid-column: 1 / -1; }
.figure-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 12px; }
.layer-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.layer-card.masked { background: #faf5ff; border-style: dashed; }
.layer-card h3 { margin: 0 0 8px; font-size: 14px; }
.point-list, .chapter-list, .figure-list { list-style: none; margin: 0; padding: 0; font-size: 13px; }
.point-list li, .chapter-list li, .figure-list li { padding: 4px 0; border-bottom: 1px dashed #e5eaf1; }
.chapter-list small, .figure-list small { display: block; color: var(--muted); }
.data-table.compact th, .data-table.compact td { padding: 5px 8px; font-size: 12px; }
.empty-state.big { padding: 48px 12px; text-align: center; color: var(--muted); }
.empty-inline { font-size: 12px; color: var(--muted); }
.muted { color: var(--muted); }
.small { font-size: 12px; }
.modal-mask { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45); display: flex; align-items: center; justify-content: center; z-index: 50; }
.modal-mask.wide .modal { width: 720px; max-width: 92vw; }
.modal { background: #fff; border-radius: 10px; padding: 18px; width: 460px; max-width: 92vw; max-height: 86vh; overflow: auto; }
.modal h3 { margin: 0 0 12px; }
.form-row { display: block; margin-bottom: 10px; }
.form-row span { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.form-row input, .form-row textarea { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 7px 9px; font: inherit; }
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
.record-pre { background: #0f172a; color: #d1fae5; border-radius: 8px; padding: 10px; font-size: 12px; max-height: 360px; overflow: auto; }
</style>
