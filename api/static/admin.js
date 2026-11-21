let isEditing = false;
let isSorting = false;
let lastWifiMapData = null;

// ちらつき防止用: 前回取得データとの差分がない場合は再描画をスキップする
let lastUserListSig = null;
let lastEntryStatusSig = null;
let lastEntryLogSig = null;

document.addEventListener('focusin', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') {
    isEditing = true;
  }
});
document.addEventListener('focusout', () => {
  isEditing = false;
});

// 「エリアごとの状態」のカードは 2026-11-20 に削除（AP の区間ごとの指示に置き換え。renderTunnelMap / openSegmentPopup）

// ======== デバイス指示（トンネルマップのアイコンから送る） ========
const DEVICE_INSTRUCTION_LABELS = [
  { value: 'none', label: 'なし' },
  { value: 'wait', label: '待て' },
  { value: 'inward', label: '奥へ' },
  { value: 'outward', label: '手前へ' },
];

// device_id -> instruction（/api/device_instructions の最新値）
let deviceInstructionMap = {};
// 直近の描画での作業者アイコンの位置（クリック判定用）
let tunnelMapHitboxes = [];
// ポップアップを開いているデバイス
let popupDeviceId = null;
// ポップアップを開いている AP の区間（segment_key）と、直近の描画での区間の位置
let popupSegmentKey = null;
let tunnelSegments = [];

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

function deviceInstructionLabel(value) {
  const o = DEVICE_INSTRUCTION_LABELS.find(o => o.value === value);
  return o ? o.label : 'なし';
}

async function saveDeviceInstruction(deviceId, instruction) {
  try {
    const res = await fetch('/api/device_instructions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, instruction })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('指示の送信に失敗しました: ' + (b.error || res.status));
      return false;
    }
    return true;
  } catch (e) {
    console.error('saveDeviceInstruction error:', e);
    alert('指示の送信に失敗しました');
    return false;
  } finally {
    isEditing = false;
  }
}

function findWorkerAt(x, y) {
  // 後から描いた（上に重なっている）アイコンを優先
  for (let i = tunnelMapHitboxes.length - 1; i >= 0; i--) {
    const h = tunnelMapHitboxes[i];
    if ((x - h.cx) ** 2 + (y - h.cy) ** 2 <= h.r ** 2) return h;
  }
  return null;
}

function openWorkerPopup(worker) {
  const popup = document.getElementById('workerPopup');
  if (!popup) return;

  popupDeviceId = worker.device_id;
  if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
  const online = (lastWifiMapData?.online_device_ids || []).includes(worker.device_id);
  const current = deviceInstructionMap[worker.device_id] || 'none';
  const label = worker.username || worker.device_id || '?';

  popup.innerHTML = `
    <div class="worker-popup-head">
      <strong>${escapeHtml(label)}</strong>
      <span class="entry-badge ${online ? 'entry-in' : 'entry-out'}">${online ? 'オンライン' : 'オフライン'}</span>
      <button type="button" class="delete is-small worker-popup-close" aria-label="閉じる"></button>
    </div>
    <p class="worker-popup-current">現在の指示: ${deviceInstructionLabel(current)}</p>
    ${worker.fire_message ? `<p class="worker-popup-fire">ウォッチの表示: ${escapeHtml(worker.fire_message)}</p>` : ''}
    <div class="buttons are-small worker-popup-buttons">
      ${DEVICE_INSTRUCTION_LABELS.map(o => `
        <button type="button" class="button ${o.value === current ? 'is-link' : ''}" data-instruction="${o.value}">${o.label}</button>
      `).join('')}
    </div>
    ${positionMethodsHtml(worker)}
  `;

  popup.querySelector('.worker-popup-close').addEventListener('click', closeWorkerPopup);
  const evalBtn = popup.querySelector('[data-position-eval]');
  if (evalBtn) {
    evalBtn.addEventListener('click', () => recordPositionEval(worker.device_id, popup));
  }
  popup.querySelectorAll('[data-instruction]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const instruction = btn.dataset.instruction;
      popup.querySelectorAll('[data-instruction]').forEach(b => { b.disabled = true; });
      const ok = await saveDeviceInstruction(worker.device_id, instruction);
      if (ok) {
        deviceInstructionMap[worker.device_id] = instruction;
        if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
        closeWorkerPopup();
      } else {
        popup.querySelectorAll('[data-instruction]').forEach(b => { b.disabled = false; });
      }
    });
  });

  // アイコンの横に表示（マップからはみ出さないように寄せる）
  popup.hidden = false;
  const wrap = popup.parentElement;
  const maxLeft = wrap.clientWidth - popup.offsetWidth - 4;
  const left = Math.max(4, Math.min(maxLeft, worker.cx + worker.r + 8));
  const top = Math.max(4, worker.cy - popup.offsetHeight / 2);
  popup.style.left = `${left}px`;
  popup.style.top = `${top}px`;
}

function closeWorkerPopup() {
  const popup = document.getElementById('workerPopup');
  if (popup) {
    popup.hidden = true;
    popup.innerHTML = '';
  }
  if (popupDeviceId === null && popupSegmentKey === null) return;
  popupDeviceId = null;
  popupSegmentKey = null;
  if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
}

// ======== AP の区間ごとの指示 ========
// マップの (x, y) にある区間（トンネルの中か、上のラベルの行）
function findSegmentAt(x, y) {
  if (!tunnelGeom) return null;
  const { tY, tH } = tunnelGeom;
  if (y < tY - 26 || y > tY + tH) return null;
  return tunnelSegments.find(seg => x >= seg.x0 && x < seg.x1) || null;
}

function openSegmentPopup(seg, x, y) {
  const popup = document.getElementById('workerPopup');
  if (!popup) return;
  popupDeviceId = null;
  popupSegmentKey = seg.key;
  if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
  const current = seg.instruction || 'none';
  const names = (lastWifiMapData?.workers || [])
    .filter(w => (seg.device_ids || []).includes(w.device_id))
    .map(w => w.username || w.device_id);
  popup.innerHTML = `
    <div class="worker-popup-head">
      <strong>${Math.round(seg.start_m)}〜${Math.round(seg.end_m)}m の区間</strong>
      <button type="button" class="delete is-small worker-popup-close" aria-label="閉じる"></button>
    </div>
    <p class="worker-popup-current">区間の指示: ${deviceInstructionLabel(current)}</p>
    <p class="worker-popup-current">いる人: ${names.length ? escapeHtml(names.join('、')) : 'いません'}</p>
    <div class="buttons are-small worker-popup-buttons">
      ${DEVICE_INSTRUCTION_LABELS.map(o => `
        <button type="button" class="button ${o.value === current ? 'is-link' : ''}" data-seg-instruction="${o.value}">${o.label}</button>
      `).join('')}
    </div>
    <p class="section-hint">今いる人全員と、あとからこの区間に入った人に届きます。</p>
  `;
  popup.querySelector('.worker-popup-close').addEventListener('click', closeWorkerPopup);
  popup.querySelectorAll('[data-seg-instruction]').forEach(btn => {
    btn.addEventListener('click', async () => {
      popup.querySelectorAll('[data-seg-instruction]').forEach(b => { b.disabled = true; });
      const ok = await saveSegmentInstruction(seg.key, btn.dataset.segInstruction);
      if (ok) {
        closeWorkerPopup();
        loadTunnelMap();
      } else {
        popup.querySelectorAll('[data-seg-instruction]').forEach(b => { b.disabled = false; });
      }
    });
  });
  popup.hidden = false;
  const wrap = popup.parentElement;
  const maxLeft = wrap.clientWidth - popup.offsetWidth - 4;
  popup.style.left = `${Math.max(4, Math.min(maxLeft, x + 8))}px`;
  popup.style.top = `${Math.max(4, y - popup.offsetHeight / 2)}px`;
}

async function saveSegmentInstruction(segmentKey, instruction) {
  try {
    const res = await fetch('/api/segment_instructions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ segment_key: segmentKey, instruction })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('区間の指示を出せませんでした: ' + (b.error || res.status));
      return false;
    }
    return true;
  } catch (e) {
    console.error('saveSegmentInstruction error:', e);
    alert('区間の指示を出せませんでした');
    return false;
  } finally {
    isEditing = false;
  }
}

// ======== 位置推定の方式（①〜④）と現地での比較 ========
const POSITION_METHOD_SHORT = {
  top2_basic: '① 上位2つ',
  top2_series: '② 上位2つ＋時系列',
  rssi_basic: '③ RSSI',
  rssi_series: '④ RSSI＋時系列',
  wifi3_series: '⑤ Wi-Fi 3点',
  fusion_series: '⑥ Wi-Fi＋BLE',
};
const POSITION_SOURCE_LABELS = { wifi: 'Wi-Fi', ble: 'BLE', wifi_legacy: 'Wi-Fi（旧形式・RSSI なし）' };

// 作業者ポップアップに出す ①〜④ の推定と「正しい位置を記録」欄
function positionMethodsHtml(worker) {
  const methods = worker.methods || {};
  const selected = lastWifiMapData?.position_method;
  const sources = (worker.sources || []).map(s => POSITION_SOURCE_LABELS[s] || s).join('・');
  // どの方式も値が無い＝直近のスキャンに登録済みの AP が無い（オフライン・AP の外など）。
  // 「—」を並べても分からないので理由を書き、記録（サーバーも 409 で断る）も出さない
  if (!Object.keys(POSITION_METHOD_SHORT).some(k => methods[k] !== null && methods[k] !== undefined)) {
    const why = worker.approx
      ? 'エリアの割当からおおよその場所に置いています。'
      : '';
    return `
      <details class="worker-popup-methods">
        <summary>推定の比較${sources ? `（${escapeHtml(sources)}）` : ''}</summary>
        <p class="worker-popup-methods-empty">今は位置の数値が出せません。直近のスキャンに、距離の分かる AP（AP位置設定・ESP32 AP）が入っていません${worker.online === false ? '（ウォッチがオフライン）' : ''}。${why}</p>
      </details>
    `;
  }
  const rows = Object.keys(POSITION_METHOD_SHORT).map(key => {
    const v = methods[key];
    const text = v === null || v === undefined ? '—' : `${Math.round(v)}m`;
    return `<tr class="${key === selected ? 'is-selected-method' : ''}"><td>${POSITION_METHOD_SHORT[key]}</td><td>${text}</td></tr>`;
  }).join('');
  return `
    <details class="worker-popup-methods">
      <summary>推定の比較${sources ? `（${escapeHtml(sources)}）` : ''}</summary>
      <table class="table is-narrow"><tbody>${rows}</tbody></table>
      <div class="worker-popup-eval">
        <label>正しい位置 <input class="input is-small" type="number" min="0" step="1" data-eval-true placeholder="m"></label>
        <button type="button" class="button is-small is-info" data-position-eval>記録</button>
      </div>
    </details>
  `;
}

async function recordPositionEval(deviceId, popup) {
  const input = popup.querySelector('[data-eval-true]');
  const text = input ? input.value.trim() : '';
  if (text === '' || isNaN(Number(text))) {
    alert('今立っている位置（入口からの m）を入れてください');
    return;
  }
  try {
    const res = await fetch('/api/position_eval', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId, true_distance_m: Number(text) })
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert('記録できませんでした: ' + (body.error || res.status));
      return;
    }
    input.value = '';
    lastPositionEvalSig = null;
    loadPositionEval();
    alert(`記録しました（正しい位置 ${Math.round(Number(text))}m）`);
  } catch (e) {
    console.error('recordPositionEval error:', e);
    alert('記録できませんでした');
  }
}

let lastPositionSettingsSig = null;
let lastPositionEvalSig = null;

async function loadPositionSettings() {
  const select = document.getElementById('positionMethodSelect');
  if (!select) return;
  try {
    const res = await fetch('/api/position_settings');
    if (!res.ok) return;
    const data = await res.json();
    const sig = JSON.stringify([data.method, data.methods]);
    if (sig === lastPositionSettingsSig) return;
    lastPositionSettingsSig = sig;
    select.innerHTML = (data.methods || []).map(m =>
      `<option value="${escapeHtml(m.key)}" ${m.key === data.method ? 'selected' : ''}>${escapeHtml(m.label)}</option>`
    ).join('');
  } catch (e) {
    console.error('loadPositionSettings error:', e);
  }
}

async function savePositionMethod() {
  const select = document.getElementById('positionMethodSelect');
  if (!select) return;
  try {
    const res = await fetch('/api/position_settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ method: select.value })
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert('保存に失敗しました: ' + (body.error || res.status));
      return;
    }
  } catch (e) {
    console.error('savePositionMethod error:', e);
    alert('保存に失敗しました');
    return;
  } finally {
    isEditing = false;
  }
  lastPositionSettingsSig = null;
  loadPositionSettings();
  loadTunnelMap();
}

// 方式ごとの誤差を、方式を横に並べた3行の表にする（マップの真上に置くので縦を短く）
async function loadPositionEval() {
  const head = document.getElementById('positionEvalHead');
  const body = document.getElementById('positionEvalBody');
  if (!head || !body) return;
  try {
    const res = await fetch('/api/position_eval');
    if (!res.ok) return;
    const data = await res.json();
    const summary = data.summary || [];
    const selected = lastWifiMapData?.position_method;
    const sig = JSON.stringify([summary, selected]);
    if (sig === lastPositionEvalSig) return;
    lastPositionEvalSig = sig;
    const fmt = v => (v === null || v === undefined ? '—' : `${v}m`);
    const cls = s => (s.key === selected ? ' class="is-selected-method"' : '');
    head.innerHTML = `<tr><th></th>${summary.map(s =>
      `<th${cls(s)} title="${escapeHtml(s.label)}">${escapeHtml(POSITION_METHOD_SHORT[s.key] || s.label)}</th>`).join('')}</tr>`;
    const row = (label, f) => `<tr><th>${label}</th>${summary.map(s => `<td${cls(s)}>${f(s)}</td>`).join('')}</tr>`;
    body.innerHTML = row('記録の数', s => s.count)
      + row('平均の誤差', s => fmt(s.mean_abs_m))
      + row('誤差の大きい側（90%）', s => fmt(s.p90_abs_m));
  } catch (e) {
    console.error('loadPositionEval error:', e);
  }
}

async function clearPositionEval() {
  if (!confirm('比較の記録をすべて削除します。元に戻せません。よろしいですか？')) return;
  try {
    const res = await fetch('/api/position_eval', { method: 'DELETE' });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('削除に失敗しました: ' + (b.error || res.status));
      return;
    }
  } catch (e) {
    console.error('clearPositionEval error:', e);
    alert('削除に失敗しました');
    return;
  }
  lastPositionEvalSig = null;
  loadPositionEval();
}

function initTunnelMapInteraction() {
  const canvas = document.getElementById('tunnelMap');
  if (!canvas) return;

  canvas.addEventListener('click', e => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    e.stopPropagation();
    if (fireMode) {
      const ratio = mapXToRatio(x);
      if (ratio !== null) placeFireLocation(ratio);
      return;
    }
    const hit = findWorkerAt(x, y);
    if (hit) {
      openWorkerPopup(hit);
      return;
    }
    const seg = findSegmentAt(x, y);
    if (seg) openSegmentPopup(seg, x, y);
    else closeWorkerPopup();
  });

  canvas.addEventListener('mousemove', e => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if (fireMode) {
      fireHoverRatio = mapXToRatio(x);
      canvas.style.cursor = fireHoverRatio === null ? 'not-allowed' : 'crosshair';
      if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
      return;
    }
    const y = e.clientY - rect.top;
    canvas.style.cursor = (findWorkerAt(x, y) || findSegmentAt(x, y)) ? 'pointer' : 'default';
  });

  canvas.addEventListener('mouseleave', () => {
    if (fireHoverRatio === null) return;
    fireHoverRatio = null;
    if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
  });

  document.addEventListener('click', e => {
    if (!popupDeviceId && !popupSegmentKey) return;
    const popup = document.getElementById('workerPopup');
    if (popup && !popup.contains(e.target)) closeWorkerPopup();
  });

  document.addEventListener('keydown', e => {
    if (e.key !== 'Escape') return;
    closeWorkerPopup();
    if (fireMode) toggleFireMode();
  });
}


// ======== 火災位置（マップをクリックして指定 → 各ウォッチに方向と距離を通知） ========
let fireMode = false;
let fireHoverRatio = null;
// renderTunnelMap が描いたトンネルの位置（クリック座標 → 比率の変換用）
let tunnelGeom = null;

function mapXToRatio(x) {
  if (!tunnelGeom) return null;
  const { tX, tW } = tunnelGeom;
  if (x < tX - 4 || x > tX + tW + 4) return null;
  return Math.max(0, Math.min(1, (x - tX) / tW));
}

// マップ横軸の比率 → 入口からの距離[m]（ap_markers の両端から求める）
function ratioToDistanceM(ratio) {
  const markers = lastWifiMapData?.ap_markers || [];
  if (markers.length < 2) return null;
  const start = markers[0].distance_m;
  const end = markers[markers.length - 1].distance_m;
  return start + ratio * (end - start);
}

function toggleFireMode() {
  fireMode = !fireMode;
  fireHoverRatio = null;
  closeWorkerPopup();
  const btn = document.getElementById('fireModeBtn');
  const canvas = document.getElementById('tunnelMap');
  if (btn) {
    btn.textContent = fireMode ? '指定をやめる' : '火災位置を指定';
    btn.classList.toggle('is-outlined', fireMode);
  }
  if (canvas) {
    canvas.classList.toggle('is-fire-mode', fireMode);
    canvas.style.cursor = 'default';
  }
  updateFireStatus();
  if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
}

async function placeFireLocation(ratio) {
  const m = ratioToDistanceM(ratio);
  const where = m === null ? 'この位置' : `入口から約${m.toFixed(0)}mの位置`;
  if (!confirm(`${where}を火災位置にして、全ウォッチに通知しますか？`)) return;
  try {
    const res = await fetch('/api/fire_location', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ratio })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('火災位置の保存に失敗しました: ' + (b.error || res.status));
      return;
    }
  } catch (e) {
    console.error('placeFireLocation error:', e);
    alert('火災位置の保存に失敗しました');
    return;
  }
  if (fireMode) toggleFireMode();
  loadTunnelMap();
}

async function clearFireLocation() {
  if (!confirm('火災位置を解除して、全ウォッチの火災通知を止めますか？')) return;
  try {
    const res = await fetch('/api/fire_location', { method: 'DELETE' });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('火災位置の解除に失敗しました: ' + (b.error || res.status));
      return;
    }
  } catch (e) {
    console.error('clearFireLocation error:', e);
    alert('火災位置の解除に失敗しました');
    return;
  }
  loadTunnelMap();
}

function updateFireStatus() {
  const status = document.getElementById('fireStatus');
  const clearBtn = document.getElementById('fireClearBtn');
  const fire = lastWifiMapData?.fire;
  const active = !!(fire && fire.active);
  if (clearBtn) clearBtn.disabled = !active;
  if (!status) return;
  status.classList.toggle('is-active', active && !fireMode);
  if (fireMode) {
    status.textContent = 'マップ上の火災の位置をクリックしてください（Escでやめる）';
  } else if (active) {
    status.textContent = `火災位置: 入口から約${Number(fire.distance_m).toFixed(0)}m（ウォッチに通知中）`;
  } else {
    status.textContent = '火災位置: 未設定';
  }
}

// 火災位置の目印（赤い帯＋ドット絵の炎）
function drawFireMarker(ctx, x, tY, tH, label, preview) {
  ctx.save();
  ctx.globalAlpha = preview ? 0.5 : 1;
  ctx.fillStyle = 'rgba(198, 40, 40, 0.18)';
  ctx.fillRect(x - 14, tY, 28, tH);
  ctx.strokeStyle = '#c62828';
  ctx.lineWidth = 2;
  ctx.setLineDash(preview ? [4, 4] : []);
  ctx.beginPath();
  ctx.moveTo(x, tY);
  ctx.lineTo(x, tY + tH);
  ctx.stroke();
  ctx.setLineDash([]);

  // 3px 単位のドットで炎を描く
  const P = 3;
  const flame = [
    '...r...',
    '..rr...',
    '..rrr..',
    '.rryrr.',
    '.ryyyr.',
    'rryyyrr',
    'ryyWyyr',
    '.ryyyr.',
  ];
  const fx = x - (flame[0].length * P) / 2;
  const fy = tY + 4;
  const colors = { r: '#c62828', y: '#ffb300', W: '#fff3c4' };
  flame.forEach((row, j) => {
    [...row].forEach((c, i) => {
      if (c === '.') return;
      ctx.fillStyle = colors[c];
      ctx.fillRect(fx + i * P, fy + j * P, P, P);
    });
  });

  if (label) {
    ctx.font = "12px 'DotGothic16', sans-serif";
    const w = ctx.measureText(label).width + 10;
    const lx = Math.max(2, Math.min(ctx.canvas.width - w - 2, x - w / 2));
    const ly = tY + tH - 22;
    ctx.fillStyle = '#c62828';
    ctx.fillRect(lx, ly, w, 18);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, lx + 5, ly + 9);
    ctx.textBaseline = 'alphabetic';
  }
  ctx.restore();
}


// ======== USER管理 ========
async function loadUserTable() {
  const body = document.getElementById('userTableBody');
  if (!body || isEditing) return;

  // 現在の行（編集中含む）を取得（既存の元キー情報も読む）
  const existingRows = Array.from(body.querySelectorAll('tr'));
  const unsaved = existingRows.map(row => {
    const inputs = row.querySelectorAll('input');
    return {
      // original_area: row.dataset.originalArea || '',
      original_user: row.dataset.originalUser || '',
      // area_id: inputs[0] ? inputs[0].value : '',
      username: inputs[0] ? inputs[0].value : '',
      device_id: inputs[1] ? inputs[1].value : ''
    };
  }).filter(r => (r.username || r.device_id));
  // }).filter(r => (r.area_id || r.username || r.device_id));

  let userList;
  try {
    const res = await fetch('/api/user');
    if (!res.ok) {
      console.error('loadUserTable: APIエラー', res.status);
      return;
    }
    userList = await res.json();
  } catch (e) {
    console.error('loadUserTable fetch error:', e);
    return;
  }
  if (!Array.isArray(userList)) {
    console.error('loadUserTable: 想定外のレスポンス形式', userList);
    return;
  }

  const sig = JSON.stringify(userList);
  if (sig === lastUserListSig && unsaved.length === 0) return;
  lastUserListSig = sig;

  body.innerHTML = '';

  // unsaved を消費しつつサーバーの行を表示（unsaved があれば上書きして表示）
  const remaining = [];
  const consumed = new Array(unsaved.length).fill(false);

  userList.forEach(item => {
    // unsaved のうち、元のキーでマッチするものを優先
    let matchedIndex = -1;
    for (let i = 0; i < unsaved.length; i++) {
      if (consumed[i]) continue;
      const u = unsaved[i];
      // if (u.original_area && u.original_area === item.area_id) { matchedIndex = i; break; }
      if (u.original_user && u.original_user === item.username) { matchedIndex = i; break; }
      if (u.username && u.username === item.username) { matchedIndex = i; break; }
    }

    // let areaVal = item.area_id;
    let usernameVal = item.username;
    let device_idVal = item.device_id || '';

    if (matchedIndex >= 0) {
      const u = unsaved[matchedIndex];
      // areaVal = u.area_id || areaVal;
      usernameVal = u.username || usernameVal;
      device_idVal = u.device_id || device_idVal;
      consumed[matchedIndex] = true;
    }

    const row = document.createElement('tr');
    // データ属性にサーバー由来のキーを保存しておく
    // row.dataset.originalArea = item.area_id || '';
    row.dataset.originalUser = item.username || '';
    row.dataset.originalDeviceId = item.device_id || '';
    row.innerHTML = `
      <td><input class="input" type="text" value="${escapeHtml(usernameVal)}"></td>
      <td><input class="input" type="text" value="${escapeHtml(device_idVal)}"></td>
      <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
    `;
    // row.innerHTML = `
    //   <td><input class="input" type="text" value="${areaVal}"></td>
    //   <td><input class="input" type="text" value="${usernameVal}"></td>
    //   <td><input class="input" type="text" value="${device_idVal}"></td>
    //   <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
    // `;
    body.appendChild(row);
  });

  // サーバーに存在しない未保存行（新規）のみ追加
  for (let i = 0; i < unsaved.length; i++) {
    if (consumed[i]) continue;
    const u = unsaved[i];
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><input class="input" type="text" value="${escapeHtml(u.username)}"></td>
      <td><input class="input" type="text" value="${escapeHtml(u.device_id)}"></td>
      <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
    `;
    body.appendChild(row);
  }
}

function addUserRow() {
  const body = document.getElementById('userTableBody');
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="input" placeholder="username"></td>
    <td><input class="input" placeholder="device_id"></td>
    <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
  `;
  body.appendChild(row);
}

async function saveUserTable() {
  const rows = document.querySelectorAll('#userTableBody tr');

  const deleteByDeviceId = new Set();
  const postDataList = [];

  for (const row of rows) {
    const cells = row.querySelectorAll('input');
    const originalDeviceId = row.dataset.originalDeviceId || '';

    const usernameVal = cells[0] ? cells[0].value.trim() : '';
    const device_idVal = cells[1] ? cells[1].value : '';

    if (!usernameVal) continue;

    if (originalDeviceId && originalDeviceId !== device_idVal) {
      deleteByDeviceId.add(originalDeviceId);
    }

    postDataList.push({ /*area_id: 'any', */username: usernameVal, device_id: device_idVal });
  }

  for (const device_id of deleteByDeviceId) {
    await fetch('/api/user', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id })
    });
  }

  const errors = [];
  for (const data of postDataList) {
    const res = await fetch('/api/user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      errors.push(`${data.username}: ${body.error || res.status}`);
    }
  }

  if (errors.length > 0) {
    alert('保存に失敗した項目があります:\n' + errors.join('\n'));
  } else {
    alert('ユーザーテーブルを保存しました');
  }
  loadUserTable();
}


// 「エリア割当設定」の表は 2026-11-21 に削除（エリアの BSSID の割当はサーバーと DB に残る。/api/area）

// ======== 入場状態表示 ========
async function loadEntryTable() {
  const body = document.getElementById('entryTableBody');
  if (!body) return;

  try {
    const res = await fetch('/api/entry_status');
    if (!res.ok) {
      console.error('入場状態の取得に失敗しました', await res.text());
      return;
    }

    const entryList = await res.json();
    body.innerHTML = '';

    entryList.forEach(item => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${escapeHtml(item.device_id)}</td>
        <td>${escapeHtml(item.area_id)}</td>
        <td>${escapeHtml(item.username || '')}</td>
      `;
      body.appendChild(row);
    });
  } catch (error) {
    console.error('入場状態取得エラー:', error);
  }
}

// ======== 共通 ========
function removeRow(button) {
  const row = button.closest('tr');
  if (!row) return;

  const originalDeviceId = row.dataset.originalDeviceId || '';

  // サーバー未保存の新規行はそのままDOMから削除
  if (!originalDeviceId) {
    row.remove();
    return;
  }

  fetch('/api/user', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: originalDeviceId })
  }).then(async res => {
    if (res.ok) {
      row.remove();
    } else {
      const txt = await res.text();
      alert('削除に失敗しました: ' + txt);
    }
  }).catch(err => {
    alert('削除エラー: ' + err);
  });
}

document.addEventListener('DOMContentLoaded', () => {
  loadUserTable();
  loadTunnelMap();
  initWifiMapRealtime();
  loadApPositionsTable();
  loadApPresetList();
  loadApNodesTable();
  loadCameras();
  loadPositionSettings();
  loadPositionEval();
  loadEntryManagement();
  initTunnelMapInteraction();

  setInterval(() => {
    if (isEditing) return;
    loadUserTable();
    loadEntryManagement();
    loadApNodesTable();
    loadCameras();
    loadPositionSettings();
    loadPositionEval();
    loadTunnelMap();
  }, 5000);
});

window.addEventListener('resize', () => {
  if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
});


// ======== トンネルマップ ========
// latest_wifi_reports が更新されたら即座にマップを再取得する（Supabase Realtime）
function initWifiMapRealtime() {
  const cfg = window.SUPABASE_CONFIG;
  if (!cfg || !cfg.url || !cfg.anonKey || !window.supabase) return;

  // 2026-11-22 から wifi_reports_v2（Wi-Fi のスキャンと通報）に行が入ったらマップを読み直す。
  // ble_reports は毎秒届くので見張らない（5 秒ごとの定期更新で反映）。続けて届いても 2 秒に 1 回まで。
  // Supabase 側で wifi_reports_v2 の Realtime を有効にし、anon キーで読める必要がある（supabase/wifi_reports_v2_report.sql）
  const client = window.supabase.createClient(cfg.url, cfg.anonKey);
  let last = 0;
  client
    .channel('wifi_reports_v2-changes')
    .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'wifi_reports_v2' }, () => {
      const now = Date.now();
      if (now - last < 2000) return;
      last = now;
      loadTunnelMap();
    })
    .subscribe();
}

async function loadTunnelMap() {
  try {
    const [mapRes, instrRes] = await Promise.all([
      fetch('/api/wifi_map'),
      fetch('/api/device_instructions')
    ]);
    if (!mapRes.ok) {
      console.error('loadTunnelMap: APIエラー', mapRes.status);
      return;
    }
    const data = await mapRes.json();
    if (instrRes.ok) {
      const instructions = await instrRes.json();
      if (Array.isArray(instructions)) {
        deviceInstructionMap = {};
        instructions.forEach(i => { deviceInstructionMap[i.device_id] = i.instruction; });
      }
    }
    lastWifiMapData = data;
    renderTunnelMap(data);
    updateFireStatus();
    if ((data.workers || []).some(w => w.report)) startReportGlowLoop();
  } catch (e) {
    console.error('wifi_map取得エラー:', e);
  }
}

// 通報中（report: true）のデバイスがいる間だけ、赤い光を明滅させ続けるループ
let reportGlowRafId = null;
function startReportGlowLoop() {
  if (reportGlowRafId) return;
  const tick = () => {
    const hasReport = lastWifiMapData && (lastWifiMapData.workers || []).some(w => w.report);
    if (!hasReport) {
      reportGlowRafId = null;
      return;
    }
    renderTunnelMap(lastWifiMapData);
    reportGlowRafId = requestAnimationFrame(tick);
  };
  reportGlowRafId = requestAnimationFrame(tick);
}

function renderTunnelMap(data) {
  const canvas = document.getElementById('tunnelMap');
  if (!canvas) return;

  const W = canvas.getBoundingClientRect().width || canvas.parentElement.clientWidth || 600;
  const H = 260;
  canvas.width = W;
  canvas.height = H;

  const ctx = canvas.getContext('2d');
  const { workers = [], ap_count = 6, ap_labels = [], area_order = [] } = data;

  const PAD_X = 44;
  const PAD_TOP = 36;
  const PAD_BOT = 36;
  const tW = W - PAD_X * 2;
  const tH = H - PAD_TOP - PAD_BOT;
  const tX = PAD_X;
  const tY = PAD_TOP;

  const C_DARK = 'rgba(25, 76, 34, 0.7)';
  const C_TEXT = '#194c22';
  const C_FILL = 'rgba(66, 133, 123, 0.25)';
  const C_GREEN = '#2d9610';
  const C_RED = '#ff4b2b';
  const C_BLUE = '#207ce5';
  const C_OFF = '#9aa5a0';
  const C_DIV = 'rgba(25, 76, 34, 0.35)';
  const FONT = "16px 'DotGothic16', sans-serif";
  const FONT_SM = "12px 'DotGothic16', sans-serif";

  ctx.clearRect(0, 0, W, H);

  // トンネル背景
  ctx.fillStyle = C_FILL;
  ctx.fillRect(tX, tY, tW, tH);
  ctx.strokeStyle = C_DARK;
  ctx.lineWidth = 3;
  ctx.strokeRect(tX, tY, tW, tH);

  // AP の区間（サーバーの segments。隣り合う AP の間）。境目に点線、上に「0〜100m」と区間の指示。
  // 区間を押すとまとめて指示を出せる（openSegmentPopup）
  const segments = Array.isArray(data.segments) ? data.segments : [];
  segments.forEach((seg, i) => {
    const x0 = tX + tW * seg.start;
    const x1 = tX + tW * seg.end;
    const active = seg.instruction && seg.instruction !== 'none';
    if (active || seg.key === popupSegmentKey) {
      ctx.fillStyle = seg.key === popupSegmentKey ? 'rgba(32, 124, 229, 0.16)' : 'rgba(255, 196, 0, 0.16)';
      ctx.fillRect(x0, tY, x1 - x0, tH);
    }
    if (i > 0) {
      ctx.strokeStyle = C_DIV;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x0, tY);
      ctx.lineTo(x0, tY + tH);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // 上のラベル: 入る幅なら「0〜100m 待て」、狭ければ指示だけ（それも入らなければ出さない）
    ctx.font = FONT_SM;
    ctx.textAlign = 'center';
    const range = `${Math.round(seg.start_m)}〜${Math.round(seg.end_m)}m`;
    const instr = active ? deviceInstructionLabel(seg.instruction) : '';
    const full = instr ? `${range} ${instr}` : range;
    const room = x1 - x0 - 4;
    const text = ctx.measureText(full).width <= room ? full : (instr && ctx.measureText(instr).width <= room ? instr : '');
    if (text) {
      ctx.fillStyle = active ? '#8a5300' : C_TEXT;
      ctx.fillText(text, (x0 + x1) / 2, tY - 12);
    }
  });
  tunnelSegments = segments.map(seg => ({ ...seg, x0: tX + tW * seg.start, x1: tX + tW * seg.end }));

  // APマーカー（トンネル下端）。実距離の位置に置く（サーバーの ap_markers。古い応答なら等間隔）
  const markers = Array.isArray(data.ap_markers) && data.ap_markers.length
    ? data.ap_markers
    : Array.from({ length: ap_count }, (_, i) => ({ label: `AP${ap_labels[i] ?? i}`, ratio: i / (ap_count - 1) }));
  // ラベルは「AP3 100m」。重なる幅では「AP3」だけ、それでも重なるなら数台おきに出す（ESP32 AP を密に並べた時など）
  ctx.font = FONT_SM;
  const longLabel = m => (m.distance_m === undefined || m.distance_m === null)
    ? m.label : `${m.label} ${Math.round(m.distance_m)}m`;
  const minGapPx = markers.slice(1).reduce((g, m, i) => Math.min(g, tW * (m.ratio - markers[i].ratio)), Infinity);
  const maxLongPx = Math.max(...markers.map(m => ctx.measureText(longLabel(m)).width));
  const maxShortPx = Math.max(...markers.map(m => ctx.measureText(m.label).width));
  const useLong = maxLongPx + 8 <= minGapPx;
  const labelEvery = useLong ? 1 : Math.max(1, Math.ceil((maxShortPx + 8) / Math.max(1, minGapPx)));
  markers.forEach((m, i) => {
    const x = tX + tW * m.ratio;
    const y = tY + tH;
    const off = m.status === 'offline';
    ctx.fillStyle = off ? C_OFF : C_BLUE;
    ctx.strokeStyle = off ? C_RED : C_DARK;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    if (off) {
      // 停止中の ESP32 AP は × を重ねる
      ctx.beginPath();
      ctx.moveTo(x - 4, y - 4); ctx.lineTo(x + 4, y + 4);
      ctx.moveTo(x + 4, y - 4); ctx.lineTo(x - 4, y + 4);
      ctx.stroke();
    }
    if (i % labelEvery !== 0 && i !== markers.length - 1) return;
    ctx.fillStyle = off ? C_RED : C_TEXT;
    ctx.font = FONT_SM;
    ctx.textAlign = 'center';
    ctx.fillText(useLong ? longLabel(m) : m.label, x, y + 22);
  });

  // 火災位置（作業者より下に描く）と、指定モード中のカーソル位置のプレビュー
  tunnelGeom = { tX, tW, tY, tH };
  const fire = data.fire;
  if (fire && fire.active && fire.ratio !== null && fire.ratio !== undefined) {
    drawFireMarker(ctx, tX + tW * fire.ratio, tY, tH, `火災 約${Number(fire.distance_m).toFixed(0)}m`, false);
  }
  if (fireMode && fireHoverRatio !== null) {
    const m = ratioToDistanceM(fireHoverRatio);
    drawFireMarker(ctx, tX + tW * fireHoverRatio, tY, tH, m === null ? 'ここ' : `ここ 約${m.toFixed(0)}m`, true);
  }

  // 作業者の円（衝突を避けてY方向にずらす）
  const R = 20;
  const centerY = tY + tH / 2;
  const wList = workers.map(w => ({
    ...w,
    cx: tX + tW * Math.max(0, Math.min(1, w.ratio)),
  })).sort((a, b) => a.cx - b.cx);

  const placed = [];
  wList.forEach(w => {
    const candidates = [centerY];
    for (let s = 1; s <= 3; s++) {
      candidates.push(centerY - s * R * 2.2);
      candidates.push(centerY + s * R * 2.2);
    }
    let cy = centerY;
    for (const c of candidates) {
      if (c < tY + R || c > tY + tH - R) continue;
      if (!placed.some(p => Math.abs(p.cx - w.cx) < R * 2.2 && Math.abs(p.cy - c) < R * 2.2)) {
        cy = c;
        break;
      }
    }
    w.cy = Math.max(tY + R, Math.min(tY + tH - R, cy));
    placed.push({ cx: w.cx, cy: w.cy });
  });

  const now = performance.now();
  wList.forEach(w => {
    // 60秒以上レポートが来ていないデバイスは「最後に見えた位置」なので薄く描く
    ctx.globalAlpha = w.online === false ? 0.4 : 1;
    if (w.report) {
      // パルスするグロー（発光）を丸の外側に描画
      const pulse = (Math.sin(now / 250) + 1) / 2; // 0〜1
      const glowR = R + 8 + pulse * 12;
      const grad = ctx.createRadialGradient(w.cx, w.cy, R * 0.5, w.cx, w.cy, glowR);
      grad.addColorStop(0, 'rgba(255,75,43,0.55)');
      grad.addColorStop(1, 'rgba(255,75,43,0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(w.cx, w.cy, glowR, 0, Math.PI * 2);
      ctx.fill();

      ctx.shadowColor = C_RED;
      ctx.shadowBlur = 10 + pulse * 16;
    }

    ctx.fillStyle = w.report ? C_RED : C_GREEN;
    ctx.strokeStyle = C_DARK;
    ctx.lineWidth = 2;
    // approx: AP位置設定に無いAPで、エリア割当の一致だけで置いたもの（エリアの中央に点線で表示）
    if (w.approx) ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.arc(w.cx, w.cy, R, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#fff';
    ctx.font = FONT_SM;
    // 円の中に収まる文字数まで切り詰める（全名はクリックしたポップアップで見られる）
    let label = (w.username || w.device_id || '?').slice(0, 6);
    while (label.length > 1 && ctx.measureText(label).width > R * 2 - 6) label = label.slice(0, -1);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, w.cx, w.cy);
    ctx.textBaseline = 'alphabetic';

    // 「なし」以外の指示が出ているデバイスには右上に指示バッジ
    const instruction = deviceInstructionMap[w.device_id] || 'none';
    if (instruction !== 'none') {
      const text = deviceInstructionLabel(instruction);
      ctx.font = FONT_SM;
      const bw = ctx.measureText(text).width + 8;
      const bx = w.cx + R * 0.4;
      const by = w.cy - R - 6;
      ctx.fillStyle = C_BLUE;
      ctx.fillRect(bx, by, bw, 18);
      ctx.strokeStyle = C_DARK;
      ctx.lineWidth = 1;
      ctx.strokeRect(bx, by, bw, 18);
      ctx.fillStyle = '#fff';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(text, bx + 4, by + 9);
      ctx.textBaseline = 'alphabetic';
    }

    // アイコンを強調（ポップアップ対象）
    if (w.device_id === popupDeviceId) {
      ctx.strokeStyle = C_BLUE;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(w.cx, w.cy, R + 4, 0, Math.PI * 2);
      ctx.stroke();
    }
  });
  ctx.globalAlpha = 1;

  tunnelMapHitboxes = wList.map(w => ({
    device_id: w.device_id,
    username: w.username,
    fire_message: w.fire_message,
    distance_m: w.distance_m,
    methods: w.methods,
    sources: w.sources,
    approx: w.approx,
    online: (data.online_device_ids || []).includes(w.device_id),
    cx: w.cx,
    cy: w.cy,
    r: R,
  }));

  // 外/奥ラベル
  ctx.fillStyle = C_TEXT;
  ctx.font = FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('外', tX - 22, tY + tH / 2);
  ctx.fillText('奥', tX + tW + 22, tY + tH / 2);
  ctx.textBaseline = 'alphabetic';

  if (workers.length === 0) {
    ctx.fillStyle = 'rgba(25,76,34,0.35)';
    ctx.font = FONT;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('作業者データなし（AP位置設定を確認してください）', tX + tW / 2, tY + tH / 2);
    ctx.textBaseline = 'alphabetic';
  }
}


// ======== AP位置設定（現場の Wi-Fi AP） ========
// MAC と入口からの距離を入れるだけ。番号はサーバーが自動で振る（app.py の handle_ap_positions）。
// 既設の 6 台は番号 0〜5（表示名 AP1, AP3, …, AP11）で、距離の列が空なら 0〜500m（100m 間隔）とみなす。
const AP_LABELS = ['1', '3', '4', '5', '6', '11'];
// 入口からの距離[m]。app.py の AP_DISTANCES_M と同じ値にする（距離が未設定の既設 AP の初期値）
const AP_POSITION_DISTANCES_M = [0, 100, 200, 300, 400, 500];

function apPositionRowHtml(item) {
  const distance = item.distance_m === null || item.distance_m === undefined ? '' : item.distance_m;
  const label = item.label || (item.position !== undefined && item.position !== null ? `AP#${item.position + 1}` : '（自動）');
  return `
    <td class="ap-position-label">${escapeHtml(label)}</td>
    <td><input class="input ap-position-mac" type="text" value="${escapeHtml(item.mac || '')}" placeholder="AA:BB:CC:DD:EE:FF"></td>
    <td><input class="input ap-position-distance" type="number" min="0" step="1" value="${escapeHtml(distance)}" placeholder="m"></td>
    <td><button class="button is-danger is-small" onclick="removeApPositionRow(this)">削除</button></td>
  `;
}

function fillApPositionRows(list, keepOriginal) {
  const body = document.getElementById('apPositionsTableBody');
  if (!body) return;
  body.innerHTML = '';
  list.forEach(item => {
    const row = document.createElement('tr');
    if (keepOriginal) row.dataset.originalMac = item.mac || '';
    if (item.position !== undefined && item.position !== null) row.dataset.position = item.position;
    row.innerHTML = apPositionRowHtml(item);
    body.appendChild(row);
  });
}

async function loadApPositionsTable() {
  try {
    const res = await fetch('/api/ap_positions');
    const data = await res.json();
    if (!res.ok) {
      console.error('ap_positions GET error:', data);
      return;
    }
    fillApPositionRows(Array.isArray(data) ? data : [], true);
  } catch (e) {
    console.error('loadApPositionsTable error:', e);
  }
}

function addApPositionRow() {
  const body = document.getElementById('apPositionsTableBody');
  const row = document.createElement('tr');
  row.innerHTML = apPositionRowHtml({});
  body.appendChild(row);
  row.querySelector('.ap-position-mac').focus();
}

function readApPositionRows() {
  return Array.from(document.querySelectorAll('#apPositionsTableBody tr')).map(row => ({
    row,
    mac: row.querySelector('.ap-position-mac')?.value.trim() || '',
    distanceText: row.querySelector('.ap-position-distance')?.value.trim() || '',
    position: row.dataset.position !== undefined ? parseInt(row.dataset.position) : null,
    originalMac: row.dataset.originalMac || '',
  }));
}

async function saveApPositionsTable() {
  const errors = [];
  for (const r of readApPositionRows()) {
    if (!r.mac && !r.distanceText) continue;   // 空の行は無視
    if (!r.mac || r.distanceText === '' || isNaN(Number(r.distanceText))) {
      errors.push(`${r.mac || '（MAC 未入力）'} → MAC と距離（m）の両方を入れてください`);
      continue;
    }
    const payload = { mac: r.mac, distance_m: Number(r.distanceText) };
    if (r.position !== null && !isNaN(r.position)) payload.position = r.position;
    if (r.originalMac && r.originalMac !== r.mac) payload.original_mac = r.originalMac;
    const res = await fetch('/api/ap_positions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const b = await res.json().catch(() => ({}));
    if (!res.ok) errors.push(`${r.mac} → ${b.error || `HTTP ${res.status}`}`);
    else if (b.warning) errors.push(b.warning);
  }
  isEditing = false;
  alert(errors.length ? '保存できなかった項目があります:\n' + errors.join('\n') : 'AP位置設定を保存しました');
  loadApPositionsTable();
  loadTunnelMap();
}

function removeApPositionRow(button) {
  const row = button.closest('tr');
  const mac = row.dataset.originalMac;
  if (!mac) {
    row.remove();
    return;
  }
  if (!confirm(`AP ${mac} を AP位置設定から削除しますか？`)) return;
  fetch('/api/ap_positions', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mac })
  }).then(res => {
    if (res.ok) {
      row.remove();
      loadTunnelMap();
    } else {
      alert('削除に失敗しました');
    }
  });
}


// ======== AP設定プリセット ========
async function loadApPresetList() {
  const select = document.getElementById('apPresetSelect');
  if (!select) return;

  try {
    const res = await fetch('/api/ap_presets');
    if (!res.ok) {
      console.error('loadApPresetList: APIエラー', res.status);
      return;
    }
    const presets = await res.json();
    if (!Array.isArray(presets)) return;

    const current = select.value;
    select.innerHTML = '<option value="">-- プリセットを選択 --</option>' +
      presets.map(p => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)}</option>`).join('');
    if (presets.some(p => p.name === current)) select.value = current;
  } catch (e) {
    console.error('loadApPresetList error:', e);
  }
}

async function loadApPreset() {
  const select = document.getElementById('apPresetSelect');
  const name = select ? select.value : '';
  if (!name) {
    alert('読み込むプリセットを選択してください');
    return;
  }

  try {
    const res = await fetch('/api/ap_presets');
    if (!res.ok) {
      alert('プリセットの取得に失敗しました');
      return;
    }
    const presets = await res.json();
    const preset = (presets || []).find(p => p.name === name);
    if (!preset) {
      alert('プリセットが見つかりません');
      return;
    }
    // 古いプリセットは位置番号だけを持つので、その番号の距離を入れる
    const list = (preset.positions || []).map(item => {
      const pos = item.position === undefined || item.position === null ? null : parseInt(item.position);
      let d = item.distance_m;
      if ((d === undefined || d === null) && pos !== null && pos >= 0 && pos < AP_POSITION_DISTANCES_M.length) {
        d = AP_POSITION_DISTANCES_M[pos];
      }
      const label = pos === null ? '（自動）' : (pos < AP_LABELS.length ? `AP${AP_LABELS[pos]}` : `AP#${pos + 1}`);
      return { mac: item.mac, position: pos, distance_m: d, label };
    });
    fillApPositionRows(list, false);

    const nameInput = document.getElementById('apPresetNameInput');
    if (nameInput) nameInput.value = name;

    alert(`プリセット「${name}」を読み込みました。内容を確認して「保存」を押すと実際のAP設定に反映されます。`);
  } catch (e) {
    console.error('loadApPreset error:', e);
    alert('プリセットの読み込みに失敗しました');
  }
}

async function saveApPreset() {
  const nameInput = document.getElementById('apPresetNameInput');
  const name = nameInput ? nameInput.value.trim() : '';
  if (!name) {
    alert('プリセット名を入力してください');
    return;
  }

  const positions = [];
  for (const r of readApPositionRows()) {
    if (!r.mac || r.distanceText === '' || isNaN(Number(r.distanceText))) continue;
    const item = { mac: r.mac, distance_m: Number(r.distanceText) };
    if (r.position !== null && !isNaN(r.position)) item.position = r.position;
    positions.push(item);
  }

  if (positions.length === 0) {
    alert('保存するAP設定がありません（MAC と距離を入れた行が必要です）');
    return;
  }

  try {
    const res = await fetch('/api/ap_presets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, positions })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('プリセットの保存に失敗しました: ' + (b.error || res.status));
      return;
    }
    alert(`プリセット「${name}」を保存しました`);
    await loadApPresetList();
    const select = document.getElementById('apPresetSelect');
    if (select) select.value = name;
  } catch (e) {
    console.error('saveApPreset error:', e);
    alert('プリセットの保存に失敗しました');
  }
}

async function deleteApPreset() {
  const select = document.getElementById('apPresetSelect');
  const name = select ? select.value : '';
  if (!name) {
    alert('削除するプリセットを選択してください');
    return;
  }
  if (!confirm(`プリセット「${name}」を削除しますか？`)) return;

  try {
    const res = await fetch('/api/ap_presets', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    });
    if (!res.ok) {
      alert('削除に失敗しました');
      return;
    }
    alert(`プリセット「${name}」を削除しました`);
    await loadApPresetList();
  } catch (e) {
    console.error('deleteApPreset error:', e);
    alert('削除に失敗しました');
  }
}


// ======== ESP32 AP ========
let lastApNodesSig = null;

async function loadApNodesTable() {
  const body = document.getElementById('apNodesTableBody');
  if (!body || isEditing) return;

  let nodes;
  try {
    const res = await fetch('/api/ap_nodes');
    if (!res.ok) {
      console.error('loadApNodesTable: APIエラー', res.status);
      return;
    }
    nodes = await res.json();
  } catch (e) {
    console.error('loadApNodesTable fetch error:', e);
    return;
  }
  if (!Array.isArray(nodes)) return;

  const sig = JSON.stringify(nodes);
  if (sig === lastApNodesSig) return;
  lastApNodesSig = sig;

  body.innerHTML = '';
  if (nodes.length === 0) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:grey;">まだ登録された ESP32 はありません（電源を入れると自動で出ます。下の欄から手で追加もできます）</td></tr>';
    return;
  }

  nodes.forEach(n => {
    const row = document.createElement('tr');
    row.dataset.mac = n.mac;
    const online = !!n.online;
    const enabled = n.enabled !== false;
    const distance = n.distance_m === null || n.distance_m === undefined ? '' : n.distance_m;
    const manual = !n.last_seen;   // 画面から追加して、まだ heartbeat が来ていない
    const kind = String(n.fw || '').startsWith('ble-') ? 'BLE' : 'Wi-Fi';
    row.innerHTML = `
      <td><span class="entry-badge ${online ? 'entry-in' : 'entry-out'}">${online ? '稼働中' : (manual ? '手動登録' : '停止')}</span> <small>${kind}</small></td>
      <td><input class="input ap-node-label" type="text" value="${escapeHtml(n.label || '')}" placeholder="A050"></td>
      <td class="mono-cell">${escapeHtml(n.mac)}</td>
      <td><input class="input ap-node-distance" type="number" min="0" step="1" value="${escapeHtml(distance)}" placeholder="未設定"></td>
      <td>
        <select class="select ap-node-enabled">
          <option value="1" ${enabled ? 'selected' : ''}>使う</option>
          <option value="0" ${enabled ? '' : 'selected'}>使わない</option>
        </select>
      </td>
      <td>${n.last_seen ? formatEntryTime(n.last_seen) : '—'}</td>
      <td class="ap-node-actions">
        <button class="button is-success is-small" onclick="saveApNode(this)">保存</button>
        <button class="button is-danger is-small" onclick="deleteApNode(this)">削除</button>
      </td>
    `;
    body.appendChild(row);
  });
}

async function saveApNode(button) {
  const row = button.closest('tr');
  const mac = row.dataset.mac;
  const distanceText = row.querySelector('.ap-node-distance').value.trim();
  const payload = {
    mac,
    label: row.querySelector('.ap-node-label').value.trim(),
    distance_m: distanceText === '' ? null : Number(distanceText),
    enabled: row.querySelector('.ap-node-enabled').value === '1',
  };
  try {
    const res = await fetch('/api/ap_nodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('保存に失敗しました: ' + (b.error || res.status));
      return;
    }
  } catch (e) {
    console.error('saveApNode error:', e);
    alert('保存に失敗しました');
    return;
  } finally {
    isEditing = false;
  }
  lastApNodesSig = null;
  loadApNodesTable();
  loadTunnelMap();
}

// 表の下の追加欄から ESP32 を登録する（上り回線が無く heartbeat を送れない ESP32 など）
async function addApNode() {
  const get = id => document.getElementById(id);
  const mac = get('apNodeNewMac').value.trim();
  const label = get('apNodeNewLabel').value.trim();
  const distanceText = get('apNodeNewDistance').value.trim();
  const kind = get('apNodeNewKind').value;
  if (!/^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$/.test(mac)) {
    alert('MAC アドレスは AA:BB:CC:DD:EE:FF の形で入れてください（BLE はシリアルに出る address=…）');
    return;
  }
  if (distanceText !== '' && isNaN(Number(distanceText))) {
    alert('入口からの距離は数値（m）で入れてください');
    return;
  }
  try {
    const res = await fetch('/api/ap_nodes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ create: true, mac, label, kind, distance_m: distanceText === '' ? null : Number(distanceText) })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('追加できませんでした: ' + (b.error || res.status));
      return;
    }
  } catch (e) {
    console.error('addApNode error:', e);
    alert('追加できませんでした');
    return;
  } finally {
    isEditing = false;
  }
  ['apNodeNewMac', 'apNodeNewLabel', 'apNodeNewDistance'].forEach(id => { get(id).value = ''; });
  lastApNodesSig = null;
  loadApNodesTable();
  loadTunnelMap();
}

async function deleteApNode(button) {
  const row = button.closest('tr');
  const mac = row.dataset.mac;
  if (!confirm(`ESP32 AP ${mac} を一覧から削除しますか？（動いていれば次の通信で再登録されます）`)) return;
  try {
    const res = await fetch('/api/ap_nodes', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac })
    });
    if (!res.ok) {
      alert('削除に失敗しました');
      return;
    }
  } catch (e) {
    console.error('deleteApNode error:', e);
    alert('削除に失敗しました');
    return;
  }
  lastApNodesSig = null;
  loadApNodesTable();
  loadTunnelMap();
}


// ======== カメラ（ESP32 カメラのコマ送り映像） ========
// 「映像を見る」を押したカメラだけ、/api/camera_frame/<id> を 1 秒ごとに取りに行く。
// 取りに行くこと自体が「見ている」合図で、サーバーがカメラに送信を指示する（app.py の camera_frame_view）。
const CAMERA_FRAME_INTERVAL_MS = 1000;
const CAMERA_AUTO_STOP_MS = 10 * 60 * 1000;
let lastCamerasSig = null;
const cameraViewers = {};   // camera_id -> { timer, objectUrl, startedAt, stopped }

async function loadCameras() {
  const grid = document.getElementById('cameraGrid');
  if (!grid) return;

  let cameras;
  try {
    const res = await fetch('/api/cameras');
    if (!res.ok) {
      console.error('loadCameras: APIエラー', res.status);
      return;
    }
    cameras = await res.json();
  } catch (e) {
    console.error('loadCameras fetch error:', e);
    return;
  }
  if (!Array.isArray(cameras)) return;

  const sig = JSON.stringify(cameras.map(c => [c.camera_id, c.label, c.distance_m, c.distance_source, c.online, c.enabled, c.wifi_rssi]));
  if (sig === lastCamerasSig) return;
  lastCamerasSig = sig;

  renderCameraTiles(grid, cameras);
  if (!isEditing) renderCameraSettings(cameras);
}

function renderCameraTiles(grid, cameras) {
  if (cameras.length === 0) {
    Object.keys(cameraViewers).forEach(stopCameraView);
    grid.innerHTML = '<p class="camera-empty">まだカメラが登録されていません（firmware/esp32cam_uplink を書き込んで電源を入れると表示されます）</p>';
    return;
  }
  grid.querySelector('.camera-empty')?.remove();

  const ids = new Set(cameras.map(c => c.camera_id));
  grid.querySelectorAll('.camera-tile').forEach(tile => {
    if (!ids.has(tile.dataset.cameraId)) {
      stopCameraView(tile.dataset.cameraId);
      tile.remove();
    }
  });

  cameras.forEach(cam => {
    let tile = grid.querySelector(`.camera-tile[data-camera-id="${CSS.escape(cam.camera_id)}"]`);
    if (!tile) {
      tile = document.createElement('div');
      tile.className = 'camera-tile';
      tile.dataset.cameraId = cam.camera_id;
      tile.innerHTML = `
        <div class="camera-head">
          <strong class="camera-label"></strong>
          <span class="entry-badge camera-badge"></span>
        </div>
        <div class="camera-view">
          <img class="camera-img" alt="" hidden>
          <p class="camera-placeholder">「映像を見る」を押すと表示します</p>
        </div>
        <div class="camera-foot">
          <button type="button" class="button is-small is-link camera-toggle">映像を見る</button>
          <span class="camera-info"></span>
        </div>
      `;
      tile.querySelector('.camera-toggle').addEventListener('click', () => {
        if (cameraViewers[cam.camera_id] && !cameraViewers[cam.camera_id].stopped) stopCameraView(cam.camera_id);
        else startCameraView(cam.camera_id);
      });
      grid.appendChild(tile);
    }
    const distance = cam.distance_m === null || cam.distance_m === undefined ? '' : `（入口から ${Math.round(cam.distance_m)}m）`;
    tile.querySelector('.camera-label').textContent = (cam.label || cam.camera_id) + distance;
    const badge = tile.querySelector('.camera-badge');
    const usable = cam.online && cam.enabled !== false;
    badge.textContent = cam.enabled === false ? '無効' : (cam.online ? '稼働中' : '停止');
    badge.classList.toggle('entry-in', usable);
    badge.classList.toggle('entry-out', !usable);
    tile.querySelector('.camera-img').alt = `${cam.label || cam.camera_id} の映像`;
  });
}

function setCameraStatus(cameraId, text) {
  const tile = document.querySelector(`.camera-tile[data-camera-id="${CSS.escape(cameraId)}"]`);
  if (tile) tile.querySelector('.camera-info').textContent = text;
}

function startCameraView(cameraId) {
  stopCameraView(cameraId);
  const viewer = { timer: null, objectUrl: null, startedAt: Date.now(), stopped: false };
  cameraViewers[cameraId] = viewer;
  const tile = document.querySelector(`.camera-tile[data-camera-id="${CSS.escape(cameraId)}"]`);
  if (tile) tile.querySelector('.camera-toggle').textContent = '止める';
  setCameraStatus(cameraId, 'カメラを起こしています…（最大 10 秒ほど）');
  fetchCameraFrame(cameraId);
}

function stopCameraView(cameraId, reason) {
  const viewer = cameraViewers[cameraId];
  if (!viewer) return;
  viewer.stopped = true;
  clearTimeout(viewer.timer);
  const tile = document.querySelector(`.camera-tile[data-camera-id="${CSS.escape(cameraId)}"]`);
  if (tile) tile.querySelector('.camera-toggle').textContent = '映像を見る';
  setCameraStatus(cameraId, reason || '');
}

async function fetchCameraFrame(cameraId) {
  const viewer = cameraViewers[cameraId];
  if (!viewer || viewer.stopped) return;
  if (Date.now() - viewer.startedAt > CAMERA_AUTO_STOP_MS) {
    stopCameraView(cameraId, '10 分たったので止めました');
    return;
  }
  // タブが隠れている間は取りに行かない（カメラも送信を止める）
  if (document.visibilityState === 'hidden') {
    viewer.timer = setTimeout(() => fetchCameraFrame(cameraId), CAMERA_FRAME_INTERVAL_MS);
    return;
  }

  try {
    const res = await fetch(`/api/camera_frame/${encodeURIComponent(cameraId)}`, { cache: 'no-store' });
    if (viewer.stopped) return;
    if (res.status === 200) {
      const blob = await res.blob();
      if (viewer.stopped) return;
      const url = URL.createObjectURL(blob);
      const tile = document.querySelector(`.camera-tile[data-camera-id="${CSS.escape(cameraId)}"]`);
      if (tile) {
        const img = tile.querySelector('.camera-img');
        img.src = url;
        img.hidden = false;
        tile.querySelector('.camera-placeholder').hidden = true;
      }
      if (viewer.objectUrl) URL.revokeObjectURL(viewer.objectUrl);
      viewer.objectUrl = url;
      const frameAt = res.headers.get('X-Frame-At');
      const age = frameAt ? Math.max(0, Math.round((Date.now() - new Date(frameAt).getTime()) / 1000)) : null;
      setCameraStatus(cameraId, frameAt ? `撮影 ${formatEntryTime(frameAt)}（${age} 秒前）` : '');
    } else if (res.status === 204) {
      setCameraStatus(cameraId, 'カメラを起こしています…（最大 10 秒ほど）');
    } else {
      setCameraStatus(cameraId, `映像を取得できません（${res.status}）`);
    }
  } catch (e) {
    console.error('fetchCameraFrame error:', e);
    setCameraStatus(cameraId, '通信エラー。再試行しています…');
  }
  if (!viewer.stopped) viewer.timer = setTimeout(() => fetchCameraFrame(cameraId), CAMERA_FRAME_INTERVAL_MS);
}

function renderCameraSettings(cameras) {
  const body = document.getElementById('cameraSettingsBody');
  if (!body) return;
  body.innerHTML = '';
  if (cameras.length === 0) {
    body.innerHTML = '<tr><td colspan="6" style="text-align:center;color:grey;">カメラはまだありません</td></tr>';
    return;
  }
  cameras.forEach(cam => {
    const row = document.createElement('tr');
    row.dataset.cameraId = cam.camera_id;
    const enabled = cam.enabled !== false;
    const distance = cam.distance_m === null || cam.distance_m === undefined ? '' : cam.distance_m;
    const linked = cam.distance_source === 'ap'
      ? `<p class="help">ESP32 AP「${escapeHtml(cam.ap_label || cam.ap_mac || '')}」と連動</p>` : '';
    row.innerHTML = `
      <td><span class="entry-badge ${cam.online ? 'entry-in' : 'entry-out'}">${cam.online ? '稼働中' : '停止'}</span></td>
      <td class="mono-cell">${escapeHtml(cam.camera_id)}</td>
      <td><input class="input camera-label-input" type="text" value="${escapeHtml(cam.label || '')}"></td>
      <td><input class="input camera-distance-input ap-node-distance" type="number" min="0" step="1" value="${escapeHtml(distance)}" placeholder="未設定">${linked}</td>
      <td>
        <select class="select camera-enabled-input">
          <option value="1" ${enabled ? 'selected' : ''}>受け取る</option>
          <option value="0" ${enabled ? '' : 'selected'}>受け取らない</option>
        </select>
      </td>
      <td class="ap-node-actions">
        <button class="button is-success is-small" onclick="saveCamera(this)">保存</button>
        <button class="button is-danger is-small" onclick="deleteCamera(this)">削除</button>
      </td>
    `;
    body.appendChild(row);
  });
}

async function saveCamera(button) {
  const row = button.closest('tr');
  const distanceText = row.querySelector('.camera-distance-input').value.trim();
  const payload = {
    camera_id: row.dataset.cameraId,
    label: row.querySelector('.camera-label-input').value.trim(),
    distance_m: distanceText === '' ? null : Number(distanceText),
    enabled: row.querySelector('.camera-enabled-input').value === '1',
  };
  try {
    const res = await fetch('/api/cameras', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      alert('保存に失敗しました: ' + (b.error || res.status));
      return;
    }
  } catch (e) {
    console.error('saveCamera error:', e);
    alert('保存に失敗しました');
    return;
  } finally {
    isEditing = false;
  }
  lastCamerasSig = null;
  loadCameras();
  lastApNodesSig = null;   // AP を兼ねるカメラは ESP32 AP 表の距離も変わる
  loadApNodesTable();
}

async function deleteCamera(button) {
  const cameraId = button.closest('tr').dataset.cameraId;
  if (!confirm(`カメラ ${cameraId} を一覧から削除しますか？（動いていれば次の通信で再登録されます）`)) return;
  try {
    const res = await fetch('/api/cameras', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ camera_id: cameraId })
    });
    if (!res.ok) {
      alert('削除に失敗しました');
      return;
    }
  } catch (e) {
    console.error('deleteCamera error:', e);
    alert('削除に失敗しました');
    return;
  }
  lastCamerasSig = null;
  loadCameras();
}


// ======== 入場管理 ========
async function loadEntryManagement() {
  try {
    const [mgmtRes, logRes] = await Promise.all([
      fetch('/api/entry_management'),
      fetch('/api/entry_log?limit=30')
    ]);
    if (mgmtRes.ok) {
      const data = await mgmtRes.json();
      const sig = JSON.stringify(data.status || []);
      if (sig !== lastEntryStatusSig) {
        lastEntryStatusSig = sig;
        renderEntryCurrentTable(data.status || []);
      }
    }
    if (logRes.ok) {
      const logData = await logRes.json();
      const sig = JSON.stringify(logData);
      if (sig !== lastEntryLogSig) {
        lastEntryLogSig = sig;
        renderEntryLogTable(logData);
      }
    }
  } catch (e) {
    console.error('loadEntryManagement error:', e);
  }
}

function renderEntryCurrentTable(statusList) {
  const body = document.getElementById('entryCurrentBody');
  if (!body) return;
  body.innerHTML = '';

  const inList = statusList.filter(s => s.status === 'in');
  const outList = statusList.filter(s => s.status !== 'in');
  [...inList, ...outList].forEach(item => {
    const row = document.createElement('tr');
    const label = item.username || item.device_id || '?';
    const isIn = item.status === 'in';
    row.innerHTML = `
      <td>${escapeHtml(label)}</td>
      <td><span class="entry-badge ${isIn ? 'entry-in' : 'entry-out'}">${isIn ? '入場中' : '退場'}</span></td>
      <td>${formatEntryTime(item.entry_time)}</td>
      <td>${formatEntryTime(item.exit_time)}</td>
    `;
    body.appendChild(row);
  });

  if (statusList.length === 0) {
    const row = document.createElement('tr');
    row.innerHTML = '<td colspan="4" style="text-align:center;color:grey;">データなし（入場APを設定してください）</td>';
    body.appendChild(row);
  }
}

function renderEntryLogTable(logList) {
  const body = document.getElementById('entryLogBody');
  if (!body) return;
  body.innerHTML = '';
  (logList || []).forEach(item => {
    const row = document.createElement('tr');
    const label = item.username || item.device_id || '?';
    const isEnter = item.event_type === 'enter';
    row.innerHTML = `
      <td>${escapeHtml(label)}</td>
      <td><span class="entry-badge ${isEnter ? 'entry-in' : 'entry-out'}">${isEnter ? '入場' : '退場'}</span></td>
      <td>${formatEntryTime(item.event_time)}</td>
    `;
    body.appendChild(row);
  });
  if (!logList || logList.length === 0) {
    const row = document.createElement('tr');
    row.innerHTML = '<td colspan="3" style="text-align:center;color:grey;">ログなし</td>';
    body.appendChild(row);
  }
}

function formatEntryTime(isoStr) {
  if (!isoStr) return '-';
  const d = new Date(isoStr);
  const mo = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${mo}/${dd} ${hh}:${mm}:${ss}`;
}



// チェックボックスの状態が変わった時に背景色を変える関数
function updateAlertStyle(checkbox) {
  // チェックボックスが含まれる一番近い「box」または「tr」を探す
  const target = checkbox.closest('.box') || checkbox.closest('tr');

  if (checkbox.checked) {
    target.classList.add('is-alerting');
  } else {
    target.classList.remove('is-alerting');
  }
}

// 動的に追加されるチェックボックスにも対応するため、イベント委譲を使用
document.addEventListener('change', function (e) {
  if (e.target && e.target.type === 'checkbox') {
    updateAlertStyle(e.target);
  }
});

// ページ読み込み時やデータ更新時にも初期状態を反映させる
function refreshAlertStyles() {
  document.querySelectorAll('input[type="checkbox"]').forEach(updateAlertStyle);
}


