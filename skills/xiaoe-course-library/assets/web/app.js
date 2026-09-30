/* 本地课程库 —— 零依赖单页应用
 * 数据：course.json（由 _work/build_web.py 生成）
 * 进度/笔记：localStorage
 */
'use strict';

const LS = {
  pos:   'nft.pos',     // { "001": 秒数 }
  done:  'nft.done',    // ["001", ...]
  notes: 'nft.notes',   // { "001": "笔记" }
  cur:   'nft.cur',     // "001"
  open:  'nft.open',    // 展开的章节
  rate:  'nft.rate',
};

const $ = s => document.querySelector(s);
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x != null) e.textContent = x; return e; };
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const save = (k, v) => localStorage.setItem(k, JSON.stringify(v));

const fmt = s => {
  if (!s || s < 0) return '—';
  const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2,'0')}:${String(x).padStart(2,'0')}` : `${m}:${String(x).padStart(2,'0')}`;
};

let COURSE, FLAT = [], BY_ID = {}, CUR = null;
let pos = load(LS.pos, {}), done = new Set(load(LS.done, []));
let notes = load(LS.notes, {}), opened = new Set(load(LS.open, []));

/* ---------------- 启动 ---------------- */
fetch('course.json').then(r => r.json()).then(init).catch(e => {
  document.body.innerHTML = `<div style="padding:60px;font:15px sans-serif;color:#e6e9ef">
    读取 course.json 失败：${e}<br><br>
    课程库需要通过 HTTP 访问（file:// 会被浏览器拦截）。<br>
    请在 <code>/home/lin/NFT</code> 下运行：<code>./web/serve.sh</code></div>`;
});

function init(c) {
  COURSE = c;
  FLAT = [];
  COURSE.chapters.forEach((ch, ci) => {
    ch.i = ci;
    ch.lessons.forEach(l => { l.ch = ch; FLAT.push(l); if (l.no != null) BY_ID[l.no] = l; });
  });
  $('#course-title').textContent = COURSE.title;
  $('#course-title').title = COURSE.title;
  buildTree();
  applyRate();
  const start = load(LS.cur, null);
  const target = (start != null && BY_ID[start]) ? BY_ID[start]
               : FLAT.find(l => l.kind === 'video' && l.available) || FLAT[0];
  select(target, true);
}

/* ---------------- 侧边栏 ---------------- */
function buildTree() {
  const tree = $('#tree'); tree.innerHTML = '';
  COURSE.chapters.forEach(ch => {
    const doneN = ch.lessons.filter(l => l.no != null && done.has(l.no)).length;
    const totN = ch.lessons.filter(l => l.kind === 'video').length;

    const box = el('div', 'ch');
    const head = el('div', 'ch-head');
    head.append(el('span', 'caret', '▶'), el('span', 'nm', ch.title));
    head.append(el('span', 'mini', totN ? `${doneN}/${totN}` : ''));
    head.onclick = () => {
      box.classList.toggle('open');
      box.classList.contains('open') ? opened.add(ch.title) : opened.delete(ch.title);
      save(LS.open, [...opened]);
    };
    box.append(head);

    const body = el('div', 'ch-body');
    ch.lessons.forEach(l => {
      const row = el('div', 'ls');
      const isDone = l.no != null && done.has(l.no);
      row.className = 'ls' + (isDone ? ' done' : '')
        + (l.kind === 'article' ? '' : l.available ? ' ready' : ' miss');
      row.append(el('span', 'no', l.no != null ? String(l.no).padStart(3, '0') : '—'));
      row.append(el('span', 'tx', l.title));
      row.append(el('span', 'du', l.kind === 'article' ? '图文'
        : fmt(l.duration || l.catalog_duration)));
      row.append(el('span', 'dot'));
      row.title = l.title;
      row.onclick = () => select(l);
      l.el = row;
      body.append(row);
    });
    box.append(body);
    if (opened.has(ch.title)) box.classList.add('open');
    ch.el = box;
    tree.append(box);
  });
  refreshProgress();
}

function refreshProgress() {
  const vids = FLAT.filter(l => l.kind === 'video');
  const d = vids.filter(l => done.has(l.no)).length;
  const pct = vids.length ? Math.round(d / vids.length * 100) : 0;
  $('#bar').style.width = pct + '%';
  $('#pct').textContent = pct + '%';
  COURSE.chapters.forEach(ch => {
    const v = ch.lessons.filter(l => l.kind === 'video');
    const dn = v.filter(l => done.has(l.no)).length;
    ch.el.querySelector('.mini').textContent = v.length ? `${dn}/${v.length}` : '';
  });
  const s = COURSE.stats || {};
  $('#stats').innerHTML =
    `<span>${s.available ?? vids.length}/${s.lessons ?? vids.length} 已下载</span>` +
    `<span>${(s.downloaded_hours ?? 0).toFixed(1)}h / ${(s.total_hours ?? 0).toFixed(1)}h</span>`;
}

/* ---------------- 选择 / 播放 ---------------- */
function select(l, silent) {
  if (!l) return;
  FLAT.forEach(x => x.el && x.el.classList.remove('active'));
  l.el && l.el.classList.add('active');
  l.el && l.el.scrollIntoView({ block: 'nearest' });

  CUR = l;
  if (l.no != null) save(LS.cur, l.no);
  if (l.ch && !l.ch.el.classList.contains('open')) {
    l.ch.el.classList.add('open'); opened.add(l.ch.title); save(LS.open, [...opened]);
  }

  $('#crumbs').textContent = `${l.ch.title}　·　第 ${l.ch.i + 1} / ${COURSE.chapters.length} 章`;
  $('#lesson-title').textContent = l.title;
  const isDone = l.no != null && done.has(l.no);
  $('#btn-mark').textContent = isDone ? '取消完成' : '标记完成';
  $('#btn-mark').classList.toggle('primary', isDone);

  const v = $('#v'), box = $('#player-box'), art = $('#article-sec');
  v.pause(); art.hidden = true;

  if (l.kind === 'article') {
    box.hidden = true;
    art.hidden = false;
    $('#article-body').innerHTML = '读取中…';
    fetch('../article/' + encodeURIComponent(l.file || (l.title + '.html')))
      .then(r => r.text()).then(h => { $('#article-body').innerHTML = h; })
      .catch(() => { $('#article-body').innerHTML =
        '<p class="dim">正文文件未找到，请重新运行 run.py content。</p>'; });
    $('#stats-line').textContent = '图文小节';
    return;
  }

  box.hidden = false;
  const ready = l.available;
  $('#no-file').hidden = ready;
  v.style.display = ready ? '' : 'none';
  v.src = ready ? '../video/' + l.file.split('/').map(encodeURIComponent).join('/') : '';
  $('#stats-line').textContent = [
    fmt(l.duration || l.catalog_duration),
    l.resolution,
    l.size ? (l.size / 1e6).toFixed(1) + ' MB' : null,
    done.has(l.no) ? '已完成' : null,
  ].filter(Boolean).join('　·　');

  // 断点续播
  const p = pos[l.no];
  $('#resume-tag').hidden = !(p > 30 && (!l.duration || p < l.duration - 30));
  if ($('#resume-tag').hidden === false) $('#resume-tag').querySelector('b').textContent = fmt(p);
  if (ready && p > 5) {
    v.addEventListener('loadedmetadata', () => {
      if (p < v.duration - 10) { v.currentTime = p; toast(`已跳到 ${fmt(p)}`); }
    }, { once: true });
  }
  if (!silent && ready) v.play().catch(() => {});

  $('#notes').value = notes[l.no] || '';
  markNotesSaved();
}

const v = () => $('#v');

v().addEventListener('timeupdate', () => {
  const el = v();
  if (!el.currentSrc || !CUR || CUR.no == null) return;
  pos[CUR.no] = Math.floor(el.currentTime);
  save(LS.pos, pos);
});
v().addEventListener('ended', () => {
  if (CUR && CUR.no != null) {
    pos[CUR.no] = Math.floor(v().duration || 0); save(LS.pos, pos);
    if (!done.has(CUR.no)) toggleDone(true);
  }
  go(1);
});

/* ---------------- 进度 / 笔记 ---------------- */
function toggleDone(force) {
  if (!CUR || CUR.no == null) return;
  const has = done.has(CUR.no);
  const now = force !== undefined ? force : !has;
  now ? done.add(CUR.no) : done.delete(CUR.no);
  save(LS.done, [...done]);
  const row = CUR.el;
  row.classList.toggle('done', now);
  $('#btn-mark').textContent = now ? '取消完成' : '标记完成';
  $('#btn-mark').classList.toggle('primary', now);
  refreshProgress();
  toast(now ? '已标记完成 ✓' : '已取消完成');
}
$('#btn-mark').onclick = () => toggleDone();

let noteTimer;
$('#notes').addEventListener('input', () => {
  if (!CUR || CUR.no == null) return;
  notes[CUR.no] = $('#notes').value;
  clearTimeout(noteTimer);
  noteTimer = setTimeout(() => { save(LS.notes, notes); markNotesSaved(); }, 500);
});
function markNotesSaved() {
  const has = $('#notes').value.trim();
  $('#notes-saved').textContent = has ? '已自动保存' : '';
}

$('#btn-export').onclick = () => {
  const L = [`# 学习进度 — ${COURSE.title}`, '', `> 导出时间：${new Date().toLocaleString('zh-CN')}`, ''];
  COURSE.chapters.forEach(ch => {
    const vids = ch.lessons.filter(l => l.kind === 'video');
    const d = vids.filter(l => done.has(l.no)).length;
    L.push(`## ${ch.title}（${d}/${vids.length}）`, '');
    ch.lessons.forEach(l => {
      const tag = l.kind === 'article' ? '图文' : (done.has(l.no) ? '✅' : pos[l.no] ? `▶ ${fmt(pos[l.no])}` : '⬜');
      L.push(`- ${tag} **${l.no != null ? String(l.no).padStart(3, '0') + ' ' : ''}${l.title}**　${fmt(l.duration)}`);
      const n = notes[l.no];
      if (n && n.trim()) L.push('', n.trim().split('\n').map(x => '  > ' + x).join('\n'), '');
    });
    L.push('');
  });
  const blob = new Blob([L.join('\n')], { type: 'text/markdown' });
  const a = el('a'); a.href = URL.createObjectURL(blob);
  a.download = '学习进度.md'; a.click();
  toast('已导出 学习进度.md');
};

/* ---------------- 导航 ---------------- */
function go(dir) {
  const i = FLAT.indexOf(CUR);
  const n = FLAT[i + dir];
  if (!n) return toast(dir > 0 ? '已是最后一节' : '已是第一节');
  if (n.kind === 'video' && !n.available) {
    toast('该小节尚未下载完成，跳到下一节已就位的');
    for (let k = i + dir; k >= 0 && k < FLAT.length; k += dir) {
      if (FLAT[k].kind === 'video' && FLAT[k].available) return select(FLAT[k]);
    }
    return toast('附近没有已下载的小节');
  }
  select(n);
}
$('#prev').onclick = () => go(-1);
$('#next').onclick = () => go(1);

/* ---------------- 搜索 ---------------- */
$('#search').addEventListener('input', e => {
  const q = e.target.value.trim().toLowerCase();
  let hits = 0;
  COURSE.chapters.forEach(ch => {
    let shown = 0;
    ch.lessons.forEach(l => {
      const hit = !q || l.title.toLowerCase().includes(q) || ch.title.toLowerCase().includes(q);
      l.el.style.display = hit ? '' : 'none';
      if (hit) shown++;
    });
    ch.el.style.display = shown ? '' : 'none';
    if (q && shown) { ch.el.classList.add('open'); hits += shown; }
  });
  if (q) toast(hits ? `${hits} 个匹配` : '无匹配');
});

/* ---------------- 倍速 ---------------- */
const RATES = [0.75, 1, 1.25, 1.5, 1.75, 2];
function applyRate() {
  const r = load(LS.rate, 1);
  $('#rate').value = String(r);
  v().playbackRate = r;
}
$('#rate').onchange = e => {
  const r = parseFloat(e.target.value);
  save(LS.rate, r); v().playbackRate = r;
  toast(`倍速 ${r}×`);
};
function shiftRate(d) {
  const cur = v().playbackRate || 1;
  const i = Math.max(0, Math.min(RATES.length - 1, RATES.findIndex(x => x >= cur - 1e-6) + d));
  $('#rate').value = String(RATES[i]); save(LS.rate, RATES[i]);
  v().playbackRate = RATES[i]; toast(`倍速 ${RATES[i]}×`);
}

/* ---------------- 快捷键 ---------------- */
document.addEventListener('keydown', e => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) {
    if (e.key === 'Escape') e.target.blur();
    return;
  }
  const el = v();
  switch (e.key) {
    case ' ': case 'k': e.preventDefault(); el.paused ? el.play() : el.pause(); break;
    case 'ArrowLeft': e.preventDefault(); el.currentTime -= 10; break;
    case 'ArrowRight': e.preventDefault(); el.currentTime += 10; break;
    case 'j': el.currentTime -= 30; toast(`−30s`); break;
    case 'l': el.currentTime += 30; toast(`+30s`); break;
    case 'ArrowUp': e.preventDefault(); el.volume = Math.min(1, el.volume + .05); toast(`音量 ${Math.round(el.volume*100)}%`); break;
    case 'ArrowDown': e.preventDefault(); el.volume = Math.max(0, el.volume - .05); toast(`音量 ${Math.round(el.volume*100)}%`); break;
    case 'f': el.requestFullscreen && el.requestFullscreen(); break;
    case 'm': el.muted = !el.muted; toast(el.muted ? '静音' : '取消静音'); break;
    case 'n': go(1); break;
    case 'p': go(-1); break;
    case 'c': toggleDone(); break;
    case '[': shiftRate(-1); break;
    case ']': shiftRate(1); break;
    case '/': e.preventDefault(); $('#search').focus(); break;
  }
});

/* ---------------- toast ---------------- */
let tt;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('show');
  clearTimeout(tt); tt = setTimeout(() => t.classList.remove('show'), 1600);
}
