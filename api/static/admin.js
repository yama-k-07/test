let isEditing = false;
let isSorting = false;
let lastWifiMapData = null;

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

  const [areas, entries, order] = await Promise.all([
    fetch('/api/area_status').then(r => r.json()),
    fetch('/api/entry_status').then(r => r.json()),
    fetch('/api/area_order').then(r => r.json())
  ]);

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

  const userList = users.map(u => `<li>${u}</li>`).join("");

  col.innerHTML = `
    <div class="box areacard">
      <h2> ${area.area_id}</h2><br>

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
          火災通報有無
        </label>
      </div>

      <div class="content">
        <strong>入場者 (${users.length})</strong>
        <ul class="entry-list">${userList}</ul>
      </div>
    </div>
  `;
  const instructionEl = col.querySelector(".instruction");
  const fireEl = col.querySelector(".fire");

  const save = () => {
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
function instructionOptions(current) {
  const list = ["none", "waiting", "evacuate_exit", "evacuate_upwind", "alert"];
  return list.map(v =>
    `<option value="${v}" ${v === current ? "selected" : ""}>${v}</option>`
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
  if (!body) return;

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

  const res = await fetch('/api/user');
  const userList = await res.json();
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
      <td><input class="input" type="text" value="${usernameVal}"></td>
      <td><input class="input" type="text" value="${device_idVal}"></td>
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
      <td><input class="input" type="text" value="${u.username}"></td>
      <td><input class="input" type="text" value="${u.device_id}"></td>
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
      <td><input class="input" type="text" value="${item.area_id}" disabled></td>
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
        <td>${item.device_id}</td>
        <td>${item.area_id}</td>
        <td>${item.username || ''}</td>
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

  const res = await fetch('/api/area');
  const list = await res.json();
  body.innerHTML = '';

  list.forEach(item => {
    const row = document.createElement('tr');
    row.dataset.originalArea = item.area_id || '';
    row.innerHTML = `
      <td><input class="input" type="text" value="${item.area_id}"></td>
      <td><input class="input" type="text" value="${item.bssid}"></td>
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
  loadApPositionsTable();
  loadEntryManagement();
  loadEntryApConfig();

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
function loadTunnelMap() {
  fetch('/api/wifi_map')
    .then(r => r.json())
    .then(data => {
      lastWifiMapData = data;
      renderTunnelMap(data);
      if ((data.workers || []).some(w => w.report)) startReportGlowLoop();
    })
    .catch(e => console.error('wifi_map取得エラー:', e));
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
  const H = 200;
  canvas.width = W;
  canvas.height = H;

  const ctx = canvas.getContext('2d');
  const { workers = [], ap_count = 6, ap_labels = [], area_order = [] } = data;

  const PAD_X = 40;
  const PAD_TOP = 28;
  const PAD_BOT = 28;
  const tW = W - PAD_X * 2;
  const tH = H - PAD_TOP - PAD_BOT;
  const tX = PAD_X;
  const tY = PAD_TOP;

  const C_DARK = 'rgba(25, 76, 34, 0.7)';
  const C_FILL = 'rgba(66, 133, 123, 0.25)';
  const C_GREEN = '#2d9610';
  const C_RED = '#ff4b2b';
  const C_BLUE = '#207ce5';
  const C_DIV = 'rgba(25, 76, 34, 0.35)';
  const FONT = "12px 'DotGothic16', sans-serif";
  const FONT_SM = "10px 'DotGothic16', sans-serif";

  ctx.clearRect(0, 0, W, H);

  // トンネル背景
  ctx.fillStyle = C_FILL;
  ctx.fillRect(tX, tY, tW, tH);
  ctx.strokeStyle = C_DARK;
  ctx.lineWidth = 3;
  ctx.strokeRect(tX, tY, tW, tH);

  // エリア区切り
  const n = area_order.length;
  if (n > 0) {
    ctx.font = FONT;
    for (let i = 0; i <= n; i++) {
      const x = tX + tW * i / n;
      if (i > 0 && i < n) {
        ctx.strokeStyle = C_DIV;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(x, tY);
        ctx.lineTo(x, tY + tH);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      if (i < n) {
        const labelX = tX + tW * (i + 0.5) / n;
        ctx.fillStyle = C_DARK;
        ctx.textAlign = 'center';
        ctx.fillText(area_order[i], labelX, tY - 6);
      }
    }
  }

  // APマーカー（トンネル下端）
  for (let i = 0; i < ap_count; i++) {
    const x = tX + tW * i / (ap_count - 1);
    const y = tY + tH;
    ctx.fillStyle = C_BLUE;
    ctx.strokeStyle = C_DARK;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = C_DARK;
    ctx.font = FONT_SM;
    ctx.textAlign = 'center';
    ctx.fillText(ap_labels[i] !== undefined ? `${ap_labels[i]}m` : `AP${i}`, x, y + 16);
  }

  // 作業者の円（衝突を避けてY方向にずらす）
  const R = 18;
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
    ctx.beginPath();
    ctx.arc(w.cx, w.cy, R, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;
    const label = (w.username || w.device_id || '?').slice(0, 6);
    ctx.fillStyle = '#fff';
    ctx.font = FONT_SM;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, w.cx, w.cy);
    ctx.textBaseline = 'alphabetic';
  });

  // 外/奥ラベル
  ctx.fillStyle = C_DARK;
  ctx.font = FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText('外', tX - 20, tY + tH / 2);
  ctx.fillText('奥', tX + tW + 20, tY + tH / 2);
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
        <td><input class="input" type="text" value="${item.mac}"></td>
        <td><input class="input" type="number" min="0" max="5" value="${item.position}" style="width:80px;"></td>
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
    <td><input class="input" type="number" min="0" max="5" placeholder="0〜5" style="width:80px;"></td>
    <td><button class="button is-danger" onclick="removeApPositionRow(this)">削除</button></td>
  `;
  body.appendChild(row);
}

async function saveApPositionsTable() {
  const rows = document.querySelectorAll('#apPositionsTableBody tr');
  const errors = [];

  for (const row of rows) {
    const inputs = row.querySelectorAll('input');
    const mac = inputs[0] ? inputs[0].value.trim() : '';
    const pos = inputs[1] ? parseInt(inputs[1].value) : NaN;
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


// ======== 入場管理 ========
async function loadEntryManagement() {
  try {
    const [mgmtRes, logRes] = await Promise.all([
      fetch('/api/entry_management'),
      fetch('/api/entry_log?limit=30')
    ]);
    if (mgmtRes.ok) {
      const data = await mgmtRes.json();
      renderEntryCurrentTable(data.status || []);
    }
    if (logRes.ok) {
      const logData = await logRes.json();
      renderEntryLogTable(logData);
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
      <td>${label}</td>
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
      <td>${label}</td>
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

// ======== 入場AP設定 ========
async function loadEntryApConfig() {
  const body = document.getElementById('entryApTableBody');
  if (!body) return;
  try {
    const res = await fetch('/api/entry_ap_config');
    if (!res.ok) return;
    const list = await res.json();
    body.innerHTML = '';
    (Array.isArray(list) ? list : []).forEach(item => {
      const row = document.createElement('tr');
      row.dataset.originalMac = item.mac || '';
      row.innerHTML = `
        <td><input class="input" type="text" value="${item.mac}"></td>
        <td><input class="input" type="text" value="${item.label || ''}"></td>
        <td><button class="button is-danger" onclick="removeEntryApRow(this)">削除</button></td>
      `;
      body.appendChild(row);
    });
  } catch (e) {
    console.error('loadEntryApConfig error:', e);
  }
}

function addEntryApRow() {
  const body = document.getElementById('entryApTableBody');
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="input" type="text" placeholder="AA:BB:CC:DD:EE:FF"></td>
    <td><input class="input" type="text" placeholder="入口ゲート"></td>
    <td><button class="button is-danger" onclick="removeEntryApRow(this)">削除</button></td>
  `;
  body.appendChild(row);
}

async function saveEntryApConfig() {
  const rows = document.querySelectorAll('#entryApTableBody tr');
  const errors = [];
  for (const row of rows) {
    const inputs = row.querySelectorAll('input');
    const mac = inputs[0] ? inputs[0].value.trim() : '';
    const label = inputs[1] ? inputs[1].value.trim() : '';
    if (!mac) continue;
    const res = await fetch('/api/entry_ap_config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac, label })
    });
    if (!res.ok) {
      const b = await res.json().catch(() => ({}));
      errors.push(`${mac}: ${b.error || res.status}`);
    }
  }
  if (errors.length > 0) {
    alert('保存に失敗しました:\n' + errors.join('\n'));
  } else {
    alert('入場AP設定を保存しました');
  }
  loadEntryApConfig();
}

function removeEntryApRow(button) {
  const row = button.closest('tr');
  const mac = row.dataset.originalMac || row.querySelector('input')?.value;
  if (!mac) { row.remove(); return; }
  fetch('/api/entry_ap_config', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mac })
  }).then(res => {
    if (res.ok) row.remove();
    else alert('削除失敗');
  });
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


