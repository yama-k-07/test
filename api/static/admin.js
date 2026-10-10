let isEditing = false;
let isSorting = false;
let lastWifiMapData = null;

// ちらつき防止用: 前回取得データとの差分がない場合は再描画をスキップする
let lastAreaBoardSig = null;
let lastAreaMapSig = null;
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

// ===== データロード =====
async function loadAreaBoard() {
  if (isEditing) return;

  let areas, entries, order;
  try {
    const [areasRes, entriesRes, orderRes] = await Promise.all([
      fetch('/api/area_status'),
      fetch('/api/entry_status'),
      fetch('/api/area_order')
    ]);
    if (!areasRes.ok || !entriesRes.ok || !orderRes.ok) {
      console.error('loadAreaBoard: APIエラー', areasRes.status, entriesRes.status, orderRes.status);
      return;
    }
    [areas, entries, order] = await Promise.all([areasRes.json(), entriesRes.json(), orderRes.json()]);
  } catch (e) {
    console.error('loadAreaBoard fetch error:', e);
    return;
  }

  if (!Array.isArray(areas) || !Array.isArray(entries) || !Array.isArray(order)) {
    console.error('loadAreaBoard: 想定外のレスポンス形式', { areas, entries, order });
    return;
  }

  const sig = JSON.stringify({ areas, entries, order });
  if (sig === lastAreaBoardSig) return;
  lastAreaBoardSig = sig;

  const board = document.getElementById("areaBoard");
  board.innerHTML = "";

  // entry を area_id ごとにまとめる
  const entryMap = {};
  entries.forEach(e => {
    if (!entryMap[e.area_id]) entryMap[e.area_id] = [];
    entryMap[e.area_id].push(e.username || e.device_id);
  });

  // 並び順を決定（order にないエリアは末尾）
  const orderedIds = [...order];
  areas.forEach(a => {
    if (!orderedIds.includes(a.area_id)) orderedIds.push(a.area_id);
  });

  orderedIds.forEach(id => {
    const area = areas.find(a => a.area_id === id);
    if (!area) return;
    const card = createAreaCard(area, entryMap[id] || []);
    board.appendChild(card);
  });

  enableSortable();
  refreshAlertStyles();
}

async function saveAreaState(areaId, instruction, fire) {
  await fetch('/api/area_status', {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify([
      { area_id: areaId, instruction, fire }
    ])
  });
  isEditing = false;
}


// ===== エリアカード生成 =====
function createAreaCard(area, users) {
  const col = document.createElement("div");
  col.className = "area-card";

  col.dataset.areaId = area.area_id;

  const userList = users.length
    ? users.map(u => `<li>${escapeHtml(u)}</li>`).join("")
    : `<li class="entry-list-empty">なし</li>`;

  col.innerHTML = `
    <div class="box areacard" data-instruction="${escapeHtml(area.instruction || 'none')}">
      <h2>${escapeHtml(area.area_id)}</h2>
      <p class="area-fire-banner">火災通報あり</p>

      <div class="field">
        <label class="label">指示</label>
        <div class="control">
          <select class="select instruction">
            ${instructionOptions(area.instruction)}
          </select>
        </div>
      </div>

      <div class="field">
        <label class="checkbox">
          <input type="checkbox" class="fire" ${area.fire ? "checked" : ""}>
          火災通報
        </label>
      </div>

      <div class="content area-entries">
        <p class="area-entries-title">入場者 <span class="area-entries-count">${users.length}</span></p>
        <ul class="entry-list">${userList}</ul>
      </div>
    </div>
  `;
  const cardEl = col.querySelector(".areacard");
  const instructionEl = col.querySelector(".instruction");
  const fireEl = col.querySelector(".fire");

  const save = () => {
    cardEl.dataset.instruction = instructionEl.value;
    isEditing = true;
    saveAreaState(
      area.area_id,
      instructionEl.value,
      fireEl.checked
    );
  };

  instructionEl.addEventListener("change", save);
  fireEl.addEventListener("change", save);

  return col;
}



// ===== 指示セレクトHTML =====
// 値（DB・デバイスに送る値）はそのまま、表示だけ日本語にする
const AREA_INSTRUCTION_LABELS = {
  none: "指示なし",
  waiting: "待機",
  evacuate_exit: "出口へ避難",
  evacuate_upwind: "風上へ避難",
  alert: "警戒",
};

function instructionOptions(current) {
  const list = ["none", "waiting", "evacuate_exit", "evacuate_upwind", "alert"];
  return list.map(v =>
    `<option value="${v}" ${v === current ? "selected" : ""}>${AREA_INSTRUCTION_LABELS[v]}</option>`
  ).join("");
}

// ===== 指示保存 =====
async function saveInstruction(areaId, instruction) {
  await fetch('/api/area_status', {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify([{ area_id: areaId, instruction, fire: false }])
  });
  isEditing = false;
}

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
  `;

  popup.querySelector('.worker-popup-close').addEventListener('click', closeWorkerPopup);
  popup.querySelectorAll('[data-instruction]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const instruction = btn.dataset.instruction;
      popup.querySelectorAll('button').forEach(b => { b.disabled = true; });
      const ok = await saveDeviceInstruction(worker.device_id, instruction);
      if (ok) {
        deviceInstructionMap[worker.device_id] = instruction;
        if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
        closeWorkerPopup();
      } else {
        popup.querySelectorAll('button').forEach(b => { b.disabled = false; });
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
  if (popupDeviceId === null) return;
  popupDeviceId = null;
  if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
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
    if (hit) openWorkerPopup(hit);
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
    canvas.style.cursor = findWorkerAt(x, e.clientY - rect.top) ? 'pointer' : 'default';
  });

  canvas.addEventListener('mouseleave', () => {
    if (fireHoverRatio === null) return;
    fireHoverRatio = null;
    if (lastWifiMapData) renderTunnelMap(lastWifiMapData);
  });

  document.addEventListener('click', e => {
    if (!popupDeviceId) return;
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
  const where = m === null ? 'この位置' : `入口から約${m.toFixed(1)}mの位置`;
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
    status.textContent = `火災位置: 入口から約${Number(fire.distance_m).toFixed(1)}m（ウォッチに通知中）`;
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


// ===== 並び替え =====
function enableSortable() {
  const board = document.getElementById("areaBoard");
  if (board._sortable) return;

  board._sortable = Sortable.create(board, {
    animation: 150,
    onStart: () => {
      isEditing = true;
      isSorting = true;
    },
    onEnd: async () => {
      await saveAreaOrder();
      isSorting = false;
      isEditing = false;
    }
  });
}



// ===== 並び順保存 =====
async function saveAreaOrder() {
  const order = Array.from(
    new Set(
      Array.from(document.querySelectorAll(".area-card"))
        .map(e => e.dataset.areaId)
    )
  );

  await fetch('/api/area_order', {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(order)
  });
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


// ======== エリア状態管理 ========
async function loadAreaTable() {
  if (isEditing || isSorting) return;
  const res = await fetch('/api/area_status');
  const areaList = await res.json();
  const body = document.getElementById('areaTableBody');
  if (!body) return;

  // 現在の編集中データを保存しておく (area_id -> {instruction, fire})
  const current = {};
  Array.from(body.querySelectorAll('tr')).forEach(r => {
    const inputs = r.querySelectorAll('input, select');
    if (inputs.length >= 3) {
      const aid = inputs[0].value;
      current[aid] = { instruction: inputs[1].value, fire: inputs[2].checked };
    }
  });

  body.innerHTML = '';

  areaList.forEach(item => {
    const row = document.createElement('tr');
    const use = current[item.area_id] || { instruction: item.instruction, fire: item.fire };
    row.innerHTML = `
      <td><input class="input" type="text" value="${escapeHtml(item.area_id)}" disabled></td>
      <td>
        <select class="select">
          <option value="none" ${use.instruction === 'none' ? 'selected' : ''}>none</option>
          <option value="waiting" ${use.instruction === 'waiting' ? 'selected' : ''}>waiting</option>
          <option value="evacuate_exit" ${use.instruction === 'evacuate_exit' ? 'selected' : ''}>evacuate_exit</option>
          <option value="evacuate_upwind" ${use.instruction === 'evacuate_upwind' ? 'selected' : ''}>evacuate_upwind</option>
          <option value="alert" ${use.instruction === 'alert' ? 'selected' : ''}>alert</option>
        </select>
      </td>
      <td><input type="checkbox" ${use.fire ? 'checked' : ''}></td>
      <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
    `;
    body.appendChild(row);
  });
}

// ======== エリア状態保存 ========
async function saveAreaTable() {
  const body = document.getElementById('areaTableBody');
  if (!body) return;

  const rows = body.querySelectorAll('tr');
  const areaData = Array.from(rows).map(row => {
    const inputs = row.querySelectorAll('input, select');
    return {
      area_id: inputs[0].value,
      instruction: inputs[1].value,
      fire: inputs[2].checked
    };
  });

  try {
    const res = await fetch('/api/area_status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(areaData)
    });

    if (res.ok) {
      alert('エリア状態を保存しました');
      await loadAreaTable(); // 更新
    } else {
      console.error('エリア状態の保存に失敗しました', await res.text());
    }
  } catch (error) {
    console.error('エリア状態保存エラー:', error);
  }
}

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

async function loadAreaMapTable() {
  const body = document.getElementById('areaTableBody');
  if (!body || isEditing) return;

  let list;
  try {
    const res = await fetch('/api/area');
    if (!res.ok) {
      console.error('loadAreaMapTable: APIエラー', res.status);
      return;
    }
    list = await res.json();
  } catch (e) {
    console.error('loadAreaMapTable fetch error:', e);
    return;
  }
  if (!Array.isArray(list)) {
    console.error('loadAreaMapTable: 想定外のレスポンス形式', list);
    return;
  }

  const sig = JSON.stringify(list);
  if (sig === lastAreaMapSig) return;
  lastAreaMapSig = sig;

  body.innerHTML = '';

  list.forEach(item => {
    const row = document.createElement('tr');
    row.dataset.originalArea = item.area_id || '';
    row.innerHTML = `
      <td><input class="input" type="text" value="${escapeHtml(item.area_id)}"></td>
      <td><input class="input" type="text" value="${escapeHtml(item.bssid)}"></td>
      <td><button class="button is-danger" onclick="removeAreaRow(this)">削除</button></td>
    `;
    body.appendChild(row);
  });
}

function addAreaRow() {
  const body = document.getElementById('areaTableBody');
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="input" placeholder="area_id"></td>
    <td><input class="input" placeholder="bssid"></td>
    <td><button class="button is-danger" onclick="removeAreaRow(this)">削除</button></td>
  `;
  body.appendChild(row);
}

async function saveAreaMapTable() {
  const rows = document.querySelectorAll('#areaTableBody tr');

  const errors = [];
  for (const row of rows) {
    const inputs = row.querySelectorAll('input');
    const areaId = inputs[0] ? inputs[0].value.trim() : '';
    if (!areaId) continue;

    const data = { area_id: areaId, bssid: inputs[1] ? inputs[1].value.trim() : '' };

    const res = await fetch('/api/area', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      errors.push(`${areaId}: ${body.error || res.status}`);
    }
  }

  if (errors.length > 0) {
    alert('保存に失敗した項目があります:\n' + errors.join('\n'));
  } else {
    alert('エリア・MACアドレス設定を保存しました');
  }
  loadAreaMapTable();
}

function removeAreaRow(button) {
  const row = button.closest('tr');
  const area_id = row.dataset.originalArea || row.querySelector('input')?.value;
  if (!area_id) {
    row.remove();
    return;
  }

  fetch('/api/area', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ area_id })
  }).then(res => {
    if (res.ok) row.remove();
    else alert('削除失敗');
  });
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
  loadAreaBoard();
  loadAreaMapTable();
  loadUserTable();
  loadTunnelMap();
  initWifiMapRealtime();
  loadApPositionsTable();
  loadApPresetList();
  loadEntryManagement();
  initTunnelMapInteraction();

  setInterval(() => {
    if (isEditing) return;
    loadAreaBoard();
    loadAreaMapTable();
    loadUserTable();
    loadEntryManagement();
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

  const client = window.supabase.createClient(cfg.url, cfg.anonKey);
  client
    .channel('latest_wifi_reports-changes')
    .on('postgres_changes', { event: '*', schema: 'public', table: 'latest_wifi_reports' }, () => {
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

  // エリア区間（サーバーの area_layout。古いサーバー応答なら等分）
  const layout = Array.isArray(data.area_layout) && data.area_layout.length
    ? data.area_layout
    : area_order.map((a, i) => ({ area_id: a, start: i / area_order.length, end: (i + 1) / area_order.length }));
  ctx.font = FONT;
  layout.forEach((seg, i) => {
    if (i > 0) {
      const x = tX + tW * seg.start;
      ctx.strokeStyle = C_DIV;
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(x, tY);
      ctx.lineTo(x, tY + tH);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.fillStyle = C_TEXT;
    ctx.textAlign = 'center';
    ctx.fillText(seg.area_id, tX + tW * (seg.start + seg.end) / 2, tY - 12);
  });

  // APマーカー（トンネル下端）。実距離の位置に置く（サーバーの ap_markers。古い応答なら等間隔）
  const markers = Array.isArray(data.ap_markers) && data.ap_markers.length
    ? data.ap_markers
    : Array.from({ length: ap_count }, (_, i) => ({ label: ap_labels[i] ?? String(i), ratio: i / (ap_count - 1) }));
  markers.forEach(m => {
    const x = tX + tW * m.ratio;
    const y = tY + tH;
    ctx.fillStyle = C_BLUE;
    ctx.strokeStyle = C_DARK;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C_TEXT;
    ctx.font = FONT_SM;
    ctx.textAlign = 'center';
    ctx.fillText(`AP${m.label}`, x, y + 22);
  });

  // 火災位置（作業者より下に描く）と、指定モード中のカーソル位置のプレビュー
  tunnelGeom = { tX, tW, tY, tH };
  const fire = data.fire;
  if (fire && fire.active && fire.ratio !== null && fire.ratio !== undefined) {
    drawFireMarker(ctx, tX + tW * fire.ratio, tY, tH, `火災 約${Number(fire.distance_m).toFixed(1)}m`, false);
  }
  if (fireMode && fireHoverRatio !== null) {
    const m = ratioToDistanceM(fireHoverRatio);
    drawFireMarker(ctx, tX + tW * fireHoverRatio, tY, tH, m === null ? 'ここ' : `ここ 約${m.toFixed(1)}m`, true);
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


// ======== AP位置設定 ========
const AP_LABELS = ['1', '3', '4', '5', '6', '11'];

function apPositionOptions(selectedPos) {
  return AP_LABELS.map((label, i) =>
    `<option value="${i}" ${i === selectedPos ? 'selected' : ''}>AP${label}</option>`
  ).join('');
}

async function loadApPositionsTable() {
  const body = document.getElementById('apPositionsTableBody');
  if (!body) return;

  try {
    const res = await fetch('/api/ap_positions');
    const data = await res.json();
    if (!res.ok) {
      console.error('ap_positions GET error:', data);
      return;
    }
    const list = Array.isArray(data) ? data : [];
    body.innerHTML = '';
    list.forEach(item => {
      const row = document.createElement('tr');
      row.dataset.originalMac = item.mac || '';
      row.innerHTML = `
        <td><input class="input" type="text" value="${escapeHtml(item.mac)}"></td>
        <td><select class="select ap-position-select">${apPositionOptions(item.position)}</select></td>
        <td><button class="button is-danger" onclick="removeApPositionRow(this)">削除</button></td>
      `;
      body.appendChild(row);
    });
  } catch (e) {
    console.error('loadApPositionsTable error:', e);
  }
}

function addApPositionRow() {
  const body = document.getElementById('apPositionsTableBody');
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="input" type="text" placeholder="AA:BB:CC:DD:EE:FF"></td>
    <td><select class="select ap-position-select">${apPositionOptions(0)}</select></td>
    <td><button class="button is-danger" onclick="removeApPositionRow(this)">削除</button></td>
  `;
  body.appendChild(row);
}

async function saveApPositionsTable() {
  const rows = document.querySelectorAll('#apPositionsTableBody tr');
  const errors = [];

  for (const row of rows) {
    const macInput = row.querySelector('input');
    const posSelect = row.querySelector('select.ap-position-select');
    const mac = macInput ? macInput.value.trim() : '';
    const pos = posSelect ? parseInt(posSelect.value) : NaN;
    if (!mac || isNaN(pos)) continue;

    const res = await fetch('/api/ap_positions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac, position: pos })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      errors.push(`${mac} → ${b.error || `HTTP ${res.status}`}`);
      console.error('ap_positions save error', mac, b);
    }
  }

  if (errors.length > 0) {
    alert('保存に失敗しました:\n' + errors.join('\n'));
  } else {
    alert('AP位置設定を保存しました');
  }
  loadApPositionsTable();
}

function removeApPositionRow(button) {
  const row = button.closest('tr');
  const mac = row.dataset.originalMac || row.querySelector('input')?.value;
  if (!mac) {
    row.remove();
    return;
  }
  fetch('/api/ap_positions', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mac })
  }).then(res => {
    if (res.ok) row.remove();
    else alert('削除失敗');
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

    const body = document.getElementById('apPositionsTableBody');
    body.innerHTML = '';
    (preset.positions || []).forEach(item => {
      const row = document.createElement('tr');
      row.dataset.originalMac = item.mac || '';
      row.innerHTML = `
        <td><input class="input" type="text" value="${escapeHtml(item.mac)}"></td>
        <td><select class="select ap-position-select">${apPositionOptions(item.position)}</select></td>
        <td><button class="button is-danger" onclick="removeApPositionRow(this)">削除</button></td>
      `;
      body.appendChild(row);
    });

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

  const rows = document.querySelectorAll('#apPositionsTableBody tr');
  const positions = [];
  for (const row of rows) {
    const macInput = row.querySelector('input');
    const posSelect = row.querySelector('select.ap-position-select');
    const mac = macInput ? macInput.value.trim() : '';
    const pos = posSelect ? parseInt(posSelect.value) : NaN;
    if (!mac || isNaN(pos)) continue;
    positions.push({ mac, position: pos });
  }

  if (positions.length === 0) {
    alert('保存するAP設定がありません');
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


