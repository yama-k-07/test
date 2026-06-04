//表表示部分
'use strict';

console.log('Hello World!!');

let InputAreaNum = 0;

InputAreaNum = window.prompt('現在のエリア数を入力してください．');


console.log(InputAreaNum);

let areas = new Array(InputAreaNum);

console.log(areas);

for (let i = 0; i < InputAreaNum; i++) {

    areas[i] = new Array(4);
    areas[i][0] = 'エリア' + (i+1);
    let InputNames = null;
    InputNames = window.prompt('エリア' + (i+1) + 'にいる従業員名を入力．例：熊谷，西條，ボボボーボ・ボーボボ');
    areas[i][1] = InputNames;
    areas[i][2] = '正常';
    areas[i][3] = false;

}
console.log(areas);

let table = document.getElementById('AreaTable');
let tr = document.createElement('tr');
const header = ['エリア名', '入場従業員名'];

for (const h of header) {

    const th = document.createElement('th');
    th.textContent = h;
    tr.appendChild(th);
}
table.appendChild(tr);

for (let i = 0; i < InputAreaNum; i++) {

    const tr = document.createElement('tr');

    const td1 = document.createElement('td');
    td1.textContent = areas[i][0];
    tr.appendChild(td1);

    const td2 = document.createElement('td');
    td2.textContent = areas[i][1];
    tr.appendChild(td2);

    table.appendChild(tr)
}

//ボタン部分
const container = document.getElementById('buttonContainer');
let selectedWrapper = null;

const stateOptions = [
  { label: '出口へ', color: 'green' },
  { label: '待機', color: 'orangered'},
  { label: '風上へ', color: 'orange'}
];

const situationOptions = [
    { label: '正常', color: 'blue' },
    { label: '火災位置', color: 'red' }
]

function createButtonElement(initialStateIndex = null) {
  const wrapper = document.createElement('div');
  wrapper.className = 'button-wrapper';

  const button = document.createElement('button');
  button.className = 'state-button';
  button.textContent = '状態を選択';
  button.dataset.state = '';

  const dropdown = document.createElement('div');
  dropdown.className = 'dropdown';

  stateOptions.forEach((option, idx) => {
    const item = document.createElement('div');
    item.textContent = option.label;
    item.addEventListener('click', () => {
      applyState(button, idx);
      dropdown.style.display = 'none';
    });
    dropdown.appendChild(item);
  });

  button.addEventListener('click', (e) => {
    // 選択状態の切り替え
    if (selectedWrapper) {
      selectedWrapper.querySelector('.state-button').classList.remove('selected');
    }
    selectedWrapper = wrapper;
    button.classList.add('selected');

    // ドロップダウン表示切り替え
    const isVisible = dropdown.style.display === 'block';
    document.querySelectorAll('.dropdown').forEach(d => d.style.display = 'none');
    dropdown.style.display = isVisible ? 'none' : 'block';
    e.stopPropagation();
  });

  if (initialStateIndex !== null) {
    applyState(button, initialStateIndex);
  }

  wrapper.appendChild(button);
  wrapper.appendChild(dropdown);

  return wrapper;
}

function applyState(button, index) {
  const option = stateOptions[index];
  button.textContent = option.label;
  button.style.backgroundColor = option.color;
  button.dataset.state = index;
  updateAreaLabels();
}


if (InputAreaNum > 0) {

    // 初期ボタン1個追加
    container.appendChild(createButtonElement());

    for (let i = 1; i < InputAreaNum; i++){

        //if (!selectedWrapper) return;
        const newBtn = createButtonElement();
        container.insertBefore(newBtn, selectedWrapper);
        
    }

}

// グローバル操作ボタン処理
document.getElementById('addLeft').addEventListener('click', () => {
  if (!selectedWrapper) return;
  const newBtn = createButtonElement();
  container.insertBefore(newBtn, selectedWrapper);
  updateAreaLabels();
});

document.getElementById('addRight').addEventListener('click', () => {
  if (!selectedWrapper) return;
  const newBtn = createButtonElement();
  if (selectedWrapper.nextSibling) {
    container.insertBefore(newBtn, selectedWrapper.nextSibling);
    updateAreaLabels();
  } else {
    container.appendChild(newBtn);
  }
});

document.getElementById('delete').addEventListener('click', () => {
  if (!selectedWrapper) return;
  const total = container.querySelectorAll('.button-wrapper').length;
  if (total <= 1) {
    alert('削除できないよ！');
    return;
  }
  container.removeChild(selectedWrapper);
  selectedWrapper = null;
  updateAreaLabels();
});
  
// 画面外クリックでドロップダウン閉じる
document.addEventListener('click', () => {
  document.querySelectorAll('.dropdown').forEach(d => d.style.display = 'none');
});

//ボタンへのラベル追加
function updateAreaLabels() {
  const wrappers = container.querySelectorAll('.button-wrapper');
  wrappers.forEach((wrapper, index) => {
    const button = wrapper.querySelector('.state-button');
    const stateIndex = button.dataset.state;
    const stateText = stateIndex !== '' ? stateOptions[stateIndex].label : '状態を選択';
    button.textContent = `${stateText}（エリア${index + 1}）`;
  });
}