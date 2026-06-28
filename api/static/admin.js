let isEditing = false;
let isSorting = false;

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

  const [areas, entries] = await Promise.all([
    fetch('/api/area_status').then(r => r.json()).catch(() => []),
    fetch('/api/entry_status').then(r => r.json()).catch(() => [])
  ]);

  const board = document.getElementById("areaBoard");
  if (!board) return;
  board.innerHTML = "";

  const areasList = Array.isArray(areas) ? areas : [];
  const entriesList = Array.isArray(entries) ? entries : [];

  // entry を area_id ごとにまとめる
  const entryMap = {};
  entriesList.forEach(e => {
    const areaId = e.area_id || e.area || e.areaId || '';
    if (!areaId) return;
    if (!entryMap[areaId]) entryMap[areaId] = [];
    entryMap[areaId].push(e.username || e.device_id || e.dev_id || '');
  });

  areasList.forEach(area => {
    const card = createAreaCard(area, entryMap[area.area_id] || []);
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
  if (!board || board._sortable) return;

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
  // 現在の index.py には /api/area_order がないため、UI 上の並び替えのみ反映して保存は行わない
  return;
}




// ======== SSID管理 ========
async function loadSsidTable() {
  const body = document.getElementById('ssidTableBody');
  if (!body) return;

  const existingRows = Array.from(body.querySelectorAll('tr'));
  const unsaved = existingRows.map(row => {
    const inputs = row.querySelectorAll('input');
    return {
      originalUsername: row.dataset.originalUsername || '',
      originalDeviceId: row.dataset.originalDeviceId || '',
      username: inputs[0] ? inputs[0].value : '',
      deviceId: inputs[1] ? inputs[1].value : ''
    };
  }).filter(r => (r.username || r.deviceId));

  const res = await fetch('/api/ssid');
  if (!res.ok) {
    body.innerHTML = '';
    return;
  }

  const ssidPayload = await res.json();
  const ssidList = Array.isArray(ssidPayload) ? ssidPayload : [];
  body.innerHTML = '';

  const consumed = new Array(unsaved.length).fill(false);

  ssidList.forEach(item => {
    let matchedIndex = -1;
    for (let i = 0; i < unsaved.length; i++) {
      if (consumed[i]) continue;
      const u = unsaved[i];
      if (u.originalUsername && u.originalUsername === item.username) { matchedIndex = i; break; }
      if (u.username && u.username === item.username) { matchedIndex = i; break; }
    }

    let usernameVal = item.username || '';
    let deviceVal = item.device_id || '';

    if (matchedIndex >= 0) {
      const u = unsaved[matchedIndex];
      usernameVal = u.username || usernameVal;
      deviceVal = u.deviceId || deviceVal;
      consumed[matchedIndex] = true;
    }

    const row = document.createElement('tr');
    row.dataset.originalUsername = item.username || '';
    row.dataset.originalDeviceId = item.device_id || '';
    row.innerHTML = `
      <td><input class="input" type="text" value="${usernameVal}"></td>
      <td><input class="input" type="text" value="${deviceVal}"></td>
      <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
    `;
    body.appendChild(row);
  });

  for (let i = 0; i < unsaved.length; i++) {
    if (consumed[i]) continue;
    const u = unsaved[i];
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><input class="input" type="text" value="${u.username}"></td>
      <td><input class="input" type="text" value="${u.deviceId}"></td>
      <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
    `;
    body.appendChild(row);
  }
}

function addSsidRow() {
  const body = document.getElementById('ssidTableBody');
  const row = document.createElement('tr');
  row.innerHTML = `
    <td><input class="input" placeholder="username"></td>
    <td><input class="input" placeholder="device_id"></td>
    <td><button class="button is-danger" onclick="removeRow(this)">削除</button></td>
  `;
  body.appendChild(row);
}

async function saveSsidTable() {
  const rows = document.querySelectorAll('#ssidTableBody tr');

  const deleteByUsername = new Set();
  const postDataList = [];

  for (const row of rows) {
    const cells = row.querySelectorAll('input');
    const originalUsername = row.dataset.originalUsername || '';

    const usernameVal = cells[0] ? cells[0].value.trim() : '';
    const deviceVal = cells[1] ? cells[1].value.trim() : '';

    if (!usernameVal) continue;

    if (originalUsername && originalUsername !== usernameVal) {
      deleteByUsername.add(originalUsername);
    }

    postDataList.push({ username: usernameVal, device_id: deviceVal });
  }

  for (const username of deleteByUsername) {
    await fetch('/api/ssid', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username })
    });
  }

  const errors = [];
  for (const data of postDataList) {
    const res = await fetch('/api/ssid', {
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
    alert('ユーザ情報を保存しました');
  }
  loadSsidTable();
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
      body.innerHTML = '';
      console.error('入場状態の取得に失敗しました', await res.text());
      return;
    }

    const entryPayload = await res.json();
    const entryList = Array.isArray(entryPayload) ? entryPayload : [];
    body.innerHTML = '';

    entryList.forEach(item => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${item.device_id || ''}</td>
        <td>${item.area_id || ''}</td>
        <td>${item.username || ''}</td>
      `;
      body.appendChild(row);
    });
  } catch (error) {
    body.innerHTML = '';
    console.error('入場状態取得エラー:', error);
  }
}

async function loadAreaMapTable() {
  const body = document.getElementById('areaTableBody');
  if (!body || isEditing) return;

  const res = await fetch('/api/area');
  if (!res.ok) {
    body.innerHTML = '';
    return;
  }

  const areaPayload = await res.json();
  const list = Array.isArray(areaPayload) ? areaPayload : [];
  body.innerHTML = '';

  list.forEach(item => {
    const row = document.createElement('tr');
    row.dataset.originalAreaId = item.area_id || '';
    row.dataset.originalBssid = item.bssid || '';
    row.innerHTML = `
      <td><input class="input" type="text" value="${item.area_id || ''}"></td>
      <td><input class="input" type="text" value="${item.bssid || ''}"></td>
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
    alert('エリア設定を保存しました');
  }
  loadAreaMapTable();
}

function removeAreaRow(button) {
  const row = button.closest('tr');
  const bssid = row.dataset.originalBssid || row.querySelectorAll('input')[1]?.value || '';
  if (!bssid) {
    row.remove();
    return;
  }

  fetch('/api/area', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bssid })
  }).then(res => {
    if (res.ok) row.remove();
    else alert('削除失敗');
  });
}


// ======== 共通 ========
function removeRow(button) {
  const row = button.closest('tr');
  if (!row) return;
  const originalUsername = row.dataset.originalUsername || '';

  if (!originalUsername) {
    row.remove();
    return;
  }

  fetch('/api/ssid', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: originalUsername })
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
  loadSsidTable();
  loadEntryTable();

  setInterval(() => {
    if (isEditing) return;
    loadAreaBoard();
    loadEntryTable();
    loadAreaMapTable();
    loadSsidTable();
  }, 5000);
});


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


