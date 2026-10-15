/* ArchLens client: renders overview, interactive UML class diagrams and the pattern catalogue.
 * No dependencies. Layout is a layered (Sugiyama-style) algorithm computed in the browser so that
 * toggling members or relation kinds re-flows the diagram. */
(function () {
  'use strict';

  const M = window.ARCHLENS_MODEL;
  if (!M) { document.getElementById('app').textContent = 'Missing assets/model.js'; return; }
  const PAGE = document.body.dataset.page;
  // Hash parameters carry the view's target and state, e.g. module.html#m=pkg.mod&class=pkg.mod.Cls
  const hashParams = () => new Map(location.hash.slice(1).split('&').filter((kv) => kv.includes('='))
    .map((kv) => { const i = kv.indexOf('='); return [kv.slice(0, i), decodeURIComponent(kv.slice(i + 1))]; }));
  const PAGE_MODULE = document.body.dataset.module || hashParams().get('m') || '';
  const withParam = (href, key, value) => `${href}${href.includes('#') ? '&' : '#'}${key}=${encodeURIComponent(value)}`;
  const CAT = M.catalog;
  const CLASSES = M.classes;
  const CATEGORY_LABEL = { creational: 'Creational', structural: 'Structural', behavioral: 'Behavioral', idiom: 'Python idioms' };
  const CATEGORIES = ['creational', 'structural', 'behavioral', 'idiom'];
  const SVGNS = 'http://www.w3.org/2000/svg';
  const VIS = { public: '+', protected: '#', private: '-' };
  const SPECIAL_KEEP = new Set(['__init__', '__new__', '__call__']);
  const PRIMARY_EXCLUDE = new Set(['idiom']);
  const RELS = ['inheritance', 'realization', 'composition', 'aggregation', 'dependency'];
  const REL_LABEL = { inheritance: 'Inheritance', realization: 'Realization', composition: 'Composition', aggregation: 'Aggregation', dependency: 'Dependency' };
  const REL_HELP = {
    inheritance: 'is-a: subclass → base class',
    realization: 'implements a Protocol',
    composition: 'owns: part created by the whole',
    aggregation: 'has: reference injected or declared',
    dependency: 'uses: in signatures or bodies',
  };

  // Supporting roles (e.g. Product, Leaf) take part in a pattern without embodying it; computed in Python.
  const _isSupport = (p) => !!p.support;

  // ------------------------------------------------------------------ small helpers
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* ignore */ } },
  };

  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'html') el.innerHTML = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const kid of kids.flat()) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  function s(tag, attrs, parent) {
    const el = document.createElementNS(SVGNS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
    if (parent) parent.appendChild(el);
    return el;
  }

  const pageHref = (kind, mod) => kind === 'overview' ? 'index.html' : kind === 'diagram' ? 'diagram.html'
    : kind === 'patterns' ? 'patterns.html' : `${kind}.html#m=${encodeURIComponent(mod)}`;
  const PACKAGES = M.packages || [];
  const classHref = (id) => withParam(pageHref('module', CLASSES[id].module), 'class', id);
  const color = (key) => (CAT[key] || {}).color || '#888';
  const truncate = (t, n) => t.length > n ? t.slice(0, n - 1) + '…' : t;
  const multLabel = (m) => m === '*' ? '0..*' : m === '1' ? '' : (m || '');

  function chip(key, role, href) {
    const c = CAT[key];
    const el = h(href ? 'a' : 'span', { class: 'chip', title: `${c.name}${role ? ' — ' + role : ''}: ${c.description}`, href },
      h('i', { style: { background: c.color } }), c.name, role ? h('span', { class: 'stereo' }, '· ' + role) : null);
    return el;
  }

  function primaryPattern(cls) {
    const ps = cls.patterns || [];
    return ps.find((p) => !_isSupport(p) && !PRIMARY_EXCLUDE.has(CAT[p.key].category))
      || ps.find((p) => !_isSupport(p)) || ps[0] || null;
  }

  const ICONS = {
    logo: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="8" height="6" rx="1.5"/><rect x="13" y="15" width="8" height="6" rx="1.5"/><rect x="3" y="15" width="8" height="6" rx="1.5"/><path d="M7 9v6M7 12h10v3"/></svg>',
    plus: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>',
    minus: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14"/></svg>',
    fit: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/></svg>',
    relayout: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7"/></svg>',
    download: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    theme: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
    close: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  };
  const iconBtn = (icon, title, onclick) => h('button', { class: 'icon-btn', title, 'aria-label': title, onclick, html: ICONS[icon] });

  // ------------------------------------------------------------------ shell
  function topbar() {
    const nav = h('nav', { class: 'nav' },
      [['overview', 'Overview'], ['diagram', 'Class diagram'], ['patterns', 'Patterns']].map(([k, label]) =>
        h('a', { href: pageHref(k), class: PAGE === k ? 'active' : null }, label)));
    const withClasses = M.modules.filter((m) => m.classes.length);
    const sel = h('select', {
      'aria-label': 'Open package or module',
      onchange: (e) => { const [k, n] = e.target.value.split('|'); if (n) location.href = pageHref(k, n); },
    }, h('option', { value: '' }, PACKAGES.length ? `Packages & modules…` : `Modules (${withClasses.length})…`),
    PACKAGES.length ? h('optgroup', { label: `Packages (${PACKAGES.length})` }, PACKAGES.map((p) =>
      h('option', { value: 'package|' + p.name, selected: PAGE === 'package' && p.name === PAGE_MODULE ? true : null }, `${p.name} (${p.classes})`))) : null,
    h('optgroup', { label: `Modules (${withClasses.length})` }, withClasses.map((m) =>
      h('option', { value: 'module|' + m.name, selected: PAGE === 'module' && m.name === PAGE_MODULE ? true : null }, `${m.name} (${m.classes.length})`))));
    const theme = iconBtn('theme', 'Toggle dark mode', () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
      root.dataset.theme = dark ? 'light' : 'dark';
      try { localStorage.setItem('archlens-theme', root.dataset.theme); } catch (e) { /* ignore */ }
    });
    return h('header', { class: 'topbar' },
      h('a', { class: 'brand', href: 'index.html', html: ICONS.logo }, h('span', {}, M.meta.title), h('small', {}, 'ArchLens')),
      nav, h('div', { class: 'spacer' }), sel, theme);
  }

  // ------------------------------------------------------------------ text measurement
  const FAMILY = getComputedStyle(document.documentElement).getPropertyValue('--mono').trim() || 'monospace';
  const SANS = getComputedStyle(document.documentElement).getPropertyValue('--sans').trim() || 'sans-serif';
  const FONTS = {
    member: `12px ${FAMILY}`, name: `bold 13px ${FAMILY}`, stereo: `italic 11px ${FAMILY}`,
    mod: `10px ${FAMILY}`, chip: `600 10px ${SANS}`, label: `10.5px ${FAMILY}`,
  };
  const ctx2d = document.createElement('canvas').getContext('2d');
  const widthCache = new Map();
  function tw(text, font) {
    const key = font + '\u0000' + text;
    let w = widthCache.get(key);
    if (w === undefined) { ctx2d.font = font; w = ctx2d.measureText(text).width; widthCache.set(key, w); }
    return w;
  }

  // ------------------------------------------------------------------ class box model
  const MAXCH = 58, LINE = 16, PADX = 10, CHIP_H = 15;

  function memberLines(cls, opt) {
    const attrs = [], methods = [];
    const visible = (name, vis) => opt.privateMembers || vis === 'public';
    if (opt.attributes) {
      for (const a of cls.attributes) {
        if (!visible(a.name, a.visibility)) continue;
        let text;
        if (a.kind === 'enum_member') text = a.name;
        else {
          text = `${VIS[a.visibility]} ${a.kind === 'property' ? '/' : ''}${a.name}`;
          if (a.type) text += `: ${a.type}`;
          if (a.scope === 'class' && a.default && a.default.length < 24) text += ` = ${a.default}`;
        }
        const klass = ['m', a.scope === 'class' && a.kind !== 'enum_member' ? 'static' : '', a.kind === 'property' ? 'prop' : ''].join(' ');
        attrs.push({ text: truncate(text, MAXCH), full: text, klass });
      }
    }
    if (opt.methods) {
      for (const m of cls.methods) {
        if (!visible(m.name, m.visibility) && !SPECIAL_KEEP.has(m.name)) continue;
        if (!opt.specialMethods && m.name.startsWith('__') && m.name.endsWith('__') && !SPECIAL_KEEP.has(m.name)) continue;
        const params = m.params.map((p) => (p.kind === 'vararg' ? '*' : p.kind === 'kwarg' ? '**' : '') + p.name + (p.annotation ? ': ' + p.annotation : ''));
        let text = `${VIS[m.visibility]} ${m.is_async ? 'async ' : ''}${m.name}(${params.join(', ')})`;
        if (m.returns) text += `: ${m.returns}`;
        const klass = ['m', m.is_static || m.is_classmethod ? 'static' : '', m.is_abstract ? 'abstract' : ''].join(' ');
        methods.push({ text: truncate(text, MAXCH), full: text, klass });
      }
    }
    return { attrs, methods };
  }

  function stereotypes(cls) {
    const st = cls.stereotypes.filter((x) => x !== 'generic' && !(x === 'abstract' && cls.stereotypes.includes('protocol')));
    const isInterface = (cls.patterns || []).some((p) => p.key === 'interface' && p.role === 'Interface');
    if (isInterface && !st.includes('protocol')) {
      const i = st.indexOf('abstract');
      if (i >= 0) st[i] = 'interface';
    }
    return st;
  }

  function measureNode(cls, opt, ghost) {
    const node = { id: cls.id, cls, ghost, chips: [] };
    const st = stereotypes(cls);
    node.stereo = st.length ? st.map((x) => `«${x}»`).join(' ') : '';
    node.title = cls.qualname;
    let w = tw(node.title, FONTS.name);
    if (node.stereo) w = Math.max(w, tw(node.stereo, FONTS.stereo));
    if (ghost) w = Math.max(w, tw(cls.module, FONTS.mod));
    const pats = ghost ? [] : [...(cls.patterns || [])].sort((a, b) => _isSupport(a) - _isSupport(b));
    const seen = new Set();
    for (const p of pats) {
      if (seen.has(p.key)) continue;
      seen.add(p.key);
      node.chips.push({ key: p.key, role: p.role, support: _isSupport(p), text: CAT[p.key].name, w: tw(CAT[p.key].name, FONTS.chip) + 12 });
    }
    const lines = ghost ? { attrs: [], methods: [] } : memberLines(cls, opt);
    node.attrs = lines.attrs; node.methods = lines.methods;
    for (const l of [...lines.attrs, ...lines.methods]) w = Math.max(w, tw(l.text, FONTS.member));
    w = Math.max(ghost ? 100 : 150, Math.ceil(w) + PADX * 2);
    // wrap chips
    const rows = []; let row = [], rowW = 0;
    for (const c of node.chips) {
      if (row.length && rowW + c.w > w - PADX * 2) { rows.push(row); row = []; rowW = 0; }
      row.push(c); rowW += c.w + 4;
    }
    if (row.length) rows.push(row);
    node.chipRows = rows;
    let y = 6;
    node.stereoY = node.stereo ? (y += 12) : null;
    node.nameY = (y += 16);
    if (ghost) node.modY = (y += 13);
    y += 6;
    node.chipY = y;
    y += rows.length * (CHIP_H + 3) + (rows.length ? 3 : 0);
    node.headH = y;
    if (!ghost) {
      node.attrY = y;
      y += (opt.attributes ? Math.max(1, node.attrs.length) * LINE + 8 : 0);
      node.methY = y;
      y += (opt.methods ? Math.max(1, node.methods.length) * LINE + 8 : 0);
    }
    node.w = w; node.h = Math.max(y, 34);
    return node;
  }

  // ------------------------------------------------------------------ layout
  /* Layered layout: structural edges (inheritance, composition, aggregation) define layers with the
   * "upper" end on top (base class above subclass, whole above part). Crossings are reduced with
   * barycenter sweeps, x positions are relaxed towards neighbours, isolated classes go to a grid. */
  function layout(nodes, edges, opts) {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const adj = new Map(nodes.map((n) => [n.id, new Set()]));
    for (const e of edges) {
      if (e.source === e.target || !byId.has(e.source) || !byId.has(e.target)) continue;
      adj.get(e.source).add(e.target); adj.get(e.target).add(e.source);
    }
    // connected components, each laid out on its own and then packed into rows
    const comp = new Map(), comps = [];
    for (const n of nodes) {
      if (comp.has(n.id) || !adj.get(n.id).size) continue;
      const members = [], stack = [n.id];
      comp.set(n.id, comps.length);
      while (stack.length) {
        const c = stack.pop(); members.push(byId.get(c));
        for (const nb of adj.get(c)) if (!comp.has(nb)) { comp.set(nb, comps.length); stack.push(nb); }
      }
      comps.push(members);
    }
    const isolated = nodes.filter((n) => !adj.get(n.id).size);
    const blocks = comps.map((members) => {
      const ids = new Set(members.map((m) => m.id));
      const pos = layered(members, edges.filter((e) => ids.has(e.source) && ids.has(e.target)), opts);
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const m of members) {
        const p = pos.get(m.id);
        x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x + m.w); y1 = Math.max(y1, p.y + m.h);
      }
      return { members, pos, x0, y0, w: x1 - x0, h: y1 - y0 };
    });
    blocks.sort((a, b) => b.members.length - a.members.length || b.w * b.h - a.w * a.h);
    const area = blocks.reduce((a, b) => a + (b.w + 80) * (b.h + 80), 0)
      + isolated.reduce((a, n) => a + (n.w + 40) * (n.h + 40), 0);
    const target = Math.max(1200, Math.sqrt(area) * 1.5, ...blocks.map((b) => b.w));
    const out = new Map();
    let x = 0, y = 0, rowH = 0;
    for (const b of blocks) {
      if (x > 0 && x + b.w > target) { x = 0; y += rowH + 100; rowH = 0; }
      for (const m of b.members) { const p = b.pos.get(m.id); out.set(m.id, { x: p.x - b.x0 + x, y: p.y - b.y0 + y }); }
      x += b.w + 100; rowH = Math.max(rowH, b.h);
    }
    if (isolated.length) {
      isolated.sort((a, b) => (a.cls.module + a.id).localeCompare(b.cls.module + b.id));
      if (blocks.length) { y += rowH + 100; }
      x = 0; rowH = 0;
      for (const n of isolated) {
        if (x > 0 && x + n.w > target) { x = 0; y += rowH + 40; rowH = 0; }
        out.set(n.id, { x, y });
        x += n.w + 32; rowH = Math.max(rowH, n.h);
      }
    }
    return out;
  }

  function layered(nodes, edges, opts) {
    const gapX = opts.gapX || 48, gapY = opts.gapY || 80, maxRow = opts.maxRowWidth || 2600;
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const succ = new Map(nodes.map((n) => [n.id, new Set()]));
    const pred = new Map(nodes.map((n) => [n.id, new Set()]));
    const undirected = new Map(nodes.map((n) => [n.id, new Set()]));

    const reaches = (from, to) => {
      const stack = [from], seen = new Set([from]);
      while (stack.length) {
        const c = stack.pop();
        if (c === to) return true;
        for (const nx of succ.get(c)) if (!seen.has(nx)) { seen.add(nx); stack.push(nx); }
      }
      return false;
    };
    const priority = { inheritance: 0, realization: 0, composition: 1, aggregation: 2, dependency: 3 };
    const sorted = [...edges].sort((a, b) => priority[a.kind] - priority[b.kind]);
    for (const e of sorted) {
      if (e.source === e.target || !byId.has(e.source) || !byId.has(e.target)) continue;
      undirected.get(e.source).add(e.target); undirected.get(e.target).add(e.source);
      const [u, v] = (e.kind === 'inheritance' || e.kind === 'realization') ? [e.target, e.source] : [e.source, e.target];
      if (succ.get(u).has(v)) continue;
      if (e.kind === 'dependency' && opts.ignoreDependencyLayers) continue;
      if (reaches(v, u)) continue; // would create a cycle
      succ.get(u).add(v); pred.get(v).add(u);
    }

    const connected = nodes;

    // longest-path layering in topological order
    const layer = new Map();
    const indeg = new Map(connected.map((n) => [n.id, pred.get(n.id).size]));
    const queue = connected.filter((n) => !indeg.get(n.id)).map((n) => n.id);
    const topo = [];
    while (queue.length) {
      const c = queue.shift();
      topo.push(c);
      for (const nx of succ.get(c)) { indeg.set(nx, indeg.get(nx) - 1); if (!indeg.get(nx)) queue.push(nx); }
    }
    for (const id of topo) {
      let l = 0;
      for (const p of pred.get(id)) l = Math.max(l, layer.get(p) + 1);
      layer.set(id, l);
    }
    // pull sources down next to their children to shorten edges
    for (let i = topo.length - 1; i >= 0; i--) {
      const id = topo[i];
      if (pred.get(id).size || !succ.get(id).size) continue;
      let l = Infinity;
      for (const nx of succ.get(id)) l = Math.min(l, layer.get(nx) - 1);
      if (l !== Infinity && l > layer.get(id)) layer.set(id, l);
    }

    // group into layers; initial order from DFS over the structure to keep families together
    const nLayers = connected.length ? Math.max(...connected.map((n) => layer.get(n.id))) + 1 : 0;
    const layers = Array.from({ length: nLayers }, () => []);
    const visited = new Set();
    const dfs = (id) => {
      if (visited.has(id)) return;
      visited.add(id);
      layers[layer.get(id)].push(id);
      for (const nx of [...succ.get(id), ...undirected.get(id)]) if (layer.has(nx)) dfs(nx);
    };
    const roots = topo.filter((id) => !pred.get(id).size);
    roots.sort((a, b) => undirected.get(b).size - undirected.get(a).size);
    for (const r of roots) dfs(r);
    for (const id of topo) dfs(id);

    // split overly wide layers into several rows
    const rows = [];
    for (const ids of layers) {
      let cur = [], w = 0;
      for (const id of ids) {
        const nw = byId.get(id).w + gapX;
        if (cur.length && w + nw > maxRow) { rows.push(cur); cur = []; w = 0; }
        cur.push(id); w += nw;
      }
      if (cur.length) rows.push(cur);
    }
    const rowOf = new Map();
    rows.forEach((r, i) => r.forEach((id) => rowOf.set(id, i)));

    // barycenter crossing reduction
    const pos = new Map();
    const index = () => rows.forEach((r) => r.forEach((id, i) => pos.set(id, i)));
    index();
    const bary = (id, dir) => {
      let sum = 0, n = 0;
      for (const nb of undirected.get(id)) {
        const r = rowOf.get(nb);
        if (r === undefined || (dir < 0 ? r >= rowOf.get(id) : r <= rowOf.get(id))) continue;
        sum += pos.get(nb); n++;
      }
      return n ? sum / n : pos.get(id);
    };
    for (let it = 0; it < 12; it++) {
      const dir = it % 2 ? 1 : -1;
      const order = dir < 0 ? rows.keys() : [...rows.keys()].reverse();
      for (const ri of order) {
        const row = rows[ri];
        const b = new Map(row.map((id) => [id, bary(id, dir)]));
        row.sort((a, c) => b.get(a) - b.get(c));
        row.forEach((id, i) => pos.set(id, i));
      }
    }

    // x coordinates: pack, then relax towards neighbours while keeping order and spacing
    const X = new Map();
    for (const row of rows) {
      let x = 0;
      for (const id of row) { X.set(id, x + byId.get(id).w / 2); x += byId.get(id).w + gapX; }
      const shift = x / 2;
      for (const id of row) X.set(id, X.get(id) - shift);
    }
    for (let it = 0; it < 24; it++) {
      const ri = it % 2 ? [...rows.keys()].reverse() : [...rows.keys()];
      for (const r of ri) {
        const row = rows[r];
        const want = row.map((id) => {
          let sum = 0, n = 0;
          for (const nb of undirected.get(id)) if (rowOf.get(nb) !== r && X.has(nb)) { sum += X.get(nb); n++; }
          return n ? sum / n : X.get(id);
        });
        const xs = want.slice();
        for (let i = 1; i < row.length; i++) {
          const min = xs[i - 1] + byId.get(row[i - 1]).w / 2 + gapX + byId.get(row[i]).w / 2;
          if (xs[i] < min) xs[i] = min;
        }
        for (let i = row.length - 2; i >= 0; i--) {
          const max = xs[i + 1] - byId.get(row[i + 1]).w / 2 - gapX - byId.get(row[i]).w / 2;
          if (xs[i] > max) xs[i] = max;
        }
        // keep the forward constraint after the backward pass
        for (let i = 1; i < row.length; i++) {
          const min = xs[i - 1] + byId.get(row[i - 1]).w / 2 + gapX + byId.get(row[i]).w / 2;
          if (xs[i] < min) xs[i] = min;
        }
        row.forEach((id, i) => X.set(id, xs[i]));
      }
    }

    // y coordinates
    const out = new Map();
    let y = 0;
    for (const row of rows) {
      const hgt = Math.max(...row.map((id) => byId.get(id).h));
      for (const id of row) {
        const n = byId.get(id);
        const x = X.get(id) - n.w / 2;
        out.set(id, { x, y });
      }
      y += hgt + gapY;
    }

    return out;
  }

  // ------------------------------------------------------------------ diagram component
  let instanceCounter = 0;

  class Diagram {
    constructor(host, config) {
      this.host = host;
      this.uid = 'd' + (++instanceCounter);
      this.config = config; // { ids, ghosts, options, onSelect, compact }
      this.opt = config.options;
      this.view = { x: 0, y: 0, k: 1 };
      this.highlightPatterns = new Set();
      this.selected = null;
      this.positions = new Map();
      this.build();
    }

    nodesAndEdges() {
      const ids = new Set(this.config.ids());
      const ghosts = new Set();
      const kinds = this.opt.relations;
      const edges = [];
      for (const r of M.relations) {
        if (!kinds.has(r.kind)) continue;
        const a = ids.has(r.source), b = ids.has(r.target);
        if (a && b) edges.push(r);
        else if (this.opt.context && (a || b)) {
          const other = a ? r.target : r.source;
          if (r.kind === 'dependency' && !this.opt.contextDependencies) continue;
          ghosts.add(other); edges.push(r);
        }
      }
      const nodes = [];
      for (const id of ids) nodes.push(measureNode(CLASSES[id], this.opt, false));
      for (const id of ghosts) if (!ids.has(id)) nodes.push(measureNode(CLASSES[id], this.opt, true));
      return { nodes, edges };
    }

    build() {
      this.host.innerHTML = '';
      const svg = this.svg = s('svg', { class: 'diagram', role: 'img', 'aria-label': 'UML class diagram' }, this.host);
      this.defs(svg);
      this.root = s('g', {}, svg);
      this.edgeLayer = s('g', { class: 'edges' }, this.root);
      this.nodeLayer = s('g', { class: 'nodes' }, this.root);
      const tb = h('div', { class: 'toolbar' },
        iconBtn('plus', 'Zoom in', () => this.zoomBy(1.25)),
        iconBtn('minus', 'Zoom out', () => this.zoomBy(0.8)),
        iconBtn('fit', 'Fit to screen', () => this.fit()),
        iconBtn('relayout', 'Re-run layout', () => { this.positions.clear(); this.refresh(true); }),
        this.config.compact || document.body.dataset.export === 'off' ? null : iconBtn('download', 'Download SVG', () => this.exportSvg()));
      this.host.append(tb);
      if (!this.config.compact) { this.statusEl = h('div', { class: 'status' }); this.host.append(this.statusEl); }
      this.bindPanZoom();
      this.refresh(true);
    }

    defs(svg) {
      const d = s('defs', {}, svg);
      const mk = (id, path, cls, w, h2, refX) => {
        for (const hl of ['', '-hl']) {
          const m = s('marker', { id: `${this.uid}-${id}${hl}`, viewBox: `0 0 ${w} ${h2}`, refX, refY: h2 / 2,
            markerWidth: w, markerHeight: h2, markerUnits: 'userSpaceOnUse', orient: 'auto' }, d);
          s('path', { d: path, class: cls + (hl ? ' marker-hl' : '') }, m);
        }
      };
      mk('tri', 'M1,1 L13,7 L1,13 Z', 'marker-hollow', 14, 14, 13);
      mk('dia', 'M1,6 L9,1 L17,6 L9,11 Z', 'marker-filled', 18, 12, 17);
      mk('odia', 'M1,6 L9,1 L17,6 L9,11 Z', 'marker-hollow', 18, 12, 17);
      mk('arrow', 'M1,1 L11,6 L1,11', 'marker-open', 12, 12, 11);
    }

    refresh(relayout) {
      const { nodes, edges } = this.nodesAndEdges();
      this.nodes = new Map(nodes.map((n) => [n.id, n]));
      this.edges = edges;
      const missing = nodes.some((n) => !this.positions.has(n.id));
      if (relayout || missing) {
        const pos = layout(nodes, edges, { ignoreDependencyLayers: !this.opt.dependencyLayers });
        for (const [id, p] of pos) if (relayout || !this.positions.has(id)) this.positions.set(id, p);
      }
      for (const n of nodes) Object.assign(n, this.positions.get(n.id));
      this.drawNodes();
      this.drawEdges();
      this.applyHighlight();
      if (relayout) requestAnimationFrame(() => this.fit());
      if (this.statusEl) {
        const real = nodes.filter((n) => !n.ghost).length;
        this.statusEl.textContent = `${real} classes${nodes.length > real ? ` + ${nodes.length - real} context` : ''} · ${edges.length} relations`;
      }
    }

    drawNodes() {
      this.nodeLayer.innerHTML = '';
      this.nodeEls = new Map();
      for (const n of this.nodes.values()) {
        const g = s('g', { class: 'node' + (n.ghost ? ' ghost' : ''), transform: `translate(${n.x},${n.y})`, 'data-id': n.id }, this.nodeLayer);
        s('title', {}, g).textContent = `${n.cls.id}${n.cls.docstring ? '\n\n' + n.cls.docstring.split('\n')[0] : ''}`;
        s('rect', { class: 'body', width: n.w, height: n.h, rx: 6 }, g);
        const prim = n.ghost ? null : primaryPattern(n.cls);
        const head = s('path', { class: 'head', d: `M0,${n.headH} V6 a6,6 0 0 1 6,-6 H${n.w - 6} a6,6 0 0 1 6,6 V${n.headH} Z` }, g);
        if (prim) {
          head.setAttribute('style', `fill:${color(prim.key)};fill-opacity:.16`);
          s('path', { d: `M0,5 V6 a6,6 0 0 1 6,-6 H${n.w - 6} a6,6 0 0 1 6,6 V5 Z`, fill: color(prim.key) }, g);
        }
        if (n.stereo) s('text', { class: 'stereo-t', x: n.w / 2, y: n.stereoY, 'text-anchor': 'middle' }, g).textContent = n.stereo;
        s('text', { class: 'name' + (n.cls.is_abstract ? ' abstract' : ''), x: n.w / 2, y: n.nameY, 'text-anchor': 'middle' }, g).textContent = n.title;
        if (n.ghost) s('text', { class: 'mod', x: n.w / 2, y: n.modY, 'text-anchor': 'middle' }, g).textContent = n.cls.module;
        let cy = n.chipY;
        for (const row of n.chipRows) {
          const total = row.reduce((a, c) => a + c.w, 0) + (row.length - 1) * 4;
          let cx = (n.w - total) / 2;
          for (const c of row) {
            const cg = s('g', { class: 'chip-g' }, g);
            s('title', {}, cg).textContent = `${CAT[c.key].name} — ${c.role}`;
            s('rect', c.support
              ? { x: cx + 0.75, y: cy + 0.75, width: c.w - 1.5, height: CHIP_H - 1.5, rx: 7, class: 'chip-out', stroke: color(c.key) }
              : { x: cx, y: cy, width: c.w, height: CHIP_H, rx: 7.5, fill: color(c.key) }, cg);
            s('text', { class: 'chip-t' + (c.support ? ' out' : ''), x: cx + c.w / 2, y: cy + 11, 'text-anchor': 'middle' }, cg).textContent = c.text;
            cx += c.w + 4;
          }
          cy += CHIP_H + 3;
        }
        if (!n.ghost) {
          s('line', { class: 'sep', x1: 0, x2: n.w, y1: n.headH, y2: n.headH }, g);
          const lines = (list, y0) => list.forEach((l, i) => {
            const t = s('text', { class: l.klass, x: PADX, y: y0 + 4 + LINE * (i + 1) - 4 }, g);
            t.textContent = l.text;
            if (l.full !== l.text) s('title', {}, t).textContent = l.full;
          });
          if (this.opt.attributes) lines(n.attrs, n.attrY);
          if (this.opt.attributes && this.opt.methods) s('line', { class: 'sep', x1: 0, x2: n.w, y1: n.methY, y2: n.methY }, g);
          if (this.opt.methods) lines(n.methods, n.methY);
        }
        this.bindNode(g, n);
        this.nodeEls.set(n.id, g);
      }
    }

    side(a, b) {
      if (a === b) return ['right', 'right'];
      if (b.y + b.h + 8 < a.y) return ['top', 'bottom'];
      if (a.y + a.h + 8 < b.y) return ['bottom', 'top'];
      return a.x + a.w / 2 < b.x + b.w / 2 ? ['right', 'left'] : ['left', 'right'];
    }

    drawEdges() {
      this.edgeLayer.innerHTML = '';
      this.edgeEls = [];
      // geometry: A = end without marker, B = end with marker (UML arrow head side)
      const geo = this.edges.map((e) => {
        const flip = e.kind === 'composition' || e.kind === 'aggregation';
        const A = this.nodes.get(flip ? e.target : e.source), B = this.nodes.get(flip ? e.source : e.target);
        const [sa, sb] = this.side(A, B);
        return { e, A, B, sa, sb };
      });
      // distribute ports along each side
      const ports = new Map();
      const addPort = (node, sideName, other, item, end) => {
        const key = node.id + '|' + sideName;
        if (!ports.has(key)) ports.set(key, []);
        ports.get(key).push({ other, item, end });
      };
      for (const g of geo) { addPort(g.A, g.sa, g.B, g, 'a'); addPort(g.B, g.sb, g.A, g, 'b'); }
      for (const [key, list] of ports) {
        const [id, sideName] = key.split('|');
        const n = this.nodes.get(id);
        const horiz = sideName === 'top' || sideName === 'bottom';
        list.sort((p, q) => horiz ? (p.other.x + p.other.w / 2) - (q.other.x + q.other.w / 2) : (p.other.y + p.other.h / 2) - (q.other.y + q.other.h / 2));
        list.forEach((p, i) => {
          const f = (i + 1) / (list.length + 1);
          let pt;
          if (sideName === 'top') pt = [n.x + n.w * f, n.y];
          else if (sideName === 'bottom') pt = [n.x + n.w * f, n.y + n.h];
          else if (sideName === 'left') pt = [n.x, n.y + Math.min(n.h, 120) * f];
          else pt = [n.x + n.w, n.y + Math.min(n.h, 120) * f];
          p.item[p.end] = pt;
        });
      }
      for (const g of geo) {
        const { e, A, B, sa, sb } = g;
        let d, labelPt;
        const [ax, ay] = g.a, [bx, by] = g.b;
        if (A === B) {
          const x = A.x + A.w, y = A.y + 14;
          d = `M${x},${y} C${x + 50},${y - 30} ${x + 50},${y + 50} ${x},${y + 26}`;
          labelPt = [x + 42, y + 12];
        } else if (sa === 'top' || sa === 'bottom') {
          const dy = Math.max(30, Math.abs(by - ay) / 2);
          const sgn = sa === 'bottom' ? 1 : -1;
          d = `M${ax},${ay} C${ax},${ay + sgn * dy} ${bx},${by - sgn * dy} ${bx},${by}`;
          labelPt = [ax + 8, ay + sgn * 16];
        } else {
          const dx = Math.max(30, Math.abs(bx - ax) / 2);
          const sgn = sa === 'right' ? 1 : -1;
          d = `M${ax},${ay} C${ax + sgn * dx},${ay} ${bx - sgn * dx},${by} ${bx},${by}`;
          labelPt = [ax + sgn * 8, ay - 5];
        }
        const grp = s('g', { class: `edge ${e.kind}`, 'data-s': e.source, 'data-t': e.target }, this.edgeLayer);
        s('title', {}, grp).textContent = `${CLASSES[e.source].name} — ${REL_LABEL[e.kind].toLowerCase()} → ${CLASSES[e.target].name}${e.label ? ` (${e.label})` : ''}`;
        s('path', { class: 'hit', d }, grp);
        const marker = { inheritance: 'tri', realization: 'tri', composition: 'dia', aggregation: 'odia', dependency: 'arrow' }[e.kind];
        const line = s('path', { class: 'line', d, 'marker-end': `url(#${this.uid}-${marker})` }, grp);
        line.dataset.marker = marker;
        if (this.opt.labels && e.label && e.kind !== 'dependency') {
          const txt = [e.label.length > 28 ? e.label.slice(0, 27) + '…' : e.label, multLabel(e.multiplicity)].filter(Boolean).join(' ');
          const anchor = sa === 'left' ? 'end' : 'start';
          s('text', { x: labelPt[0], y: labelPt[1] + (sa === 'top' ? -2 : sa === 'bottom' ? 8 : 0), 'text-anchor': anchor }, grp).textContent = txt;
        } else if (this.opt.labels && e.label && e.kind === 'dependency' && e.label.startsWith('«')) {
          s('text', { x: (ax + bx) / 2, y: (ay + by) / 2 }, grp).textContent = e.label;
        }
        this.edgeEls.push(grp);
      }
    }

    // --------------------------------------------------------- interaction
    applyTransform() {
      const { x, y, k } = this.view;
      this.root.setAttribute('transform', `translate(${x},${y}) scale(${k})`);
    }

    zoomBy(f, cx, cy) {
      const r = this.svg.getBoundingClientRect();
      cx = cx ?? r.width / 2; cy = cy ?? r.height / 2;
      const k = Math.min(4, Math.max(0.05, this.view.k * f));
      const ratio = k / this.view.k;
      this.view.x = cx - (cx - this.view.x) * ratio;
      this.view.y = cy - (cy - this.view.y) * ratio;
      this.view.k = k;
      this.applyTransform();
    }

    bbox(ids) {
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const n of this.nodes.values()) {
        if (ids && !ids.has(n.id)) continue;
        x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y); x1 = Math.max(x1, n.x + n.w); y1 = Math.max(y1, n.y + n.h);
      }
      return x0 === Infinity ? { x0: 0, y0: 0, x1: 100, y1: 100 } : { x0, y0, x1, y1 };
    }

    fit(ids, maxK) {
      const r = this.svg.getBoundingClientRect();
      if (!r.width || !r.height) return;
      const b = this.bbox(ids);
      const pad = 40;
      const k = Math.min((r.width - pad * 2) / (b.x1 - b.x0 || 1), (r.height - pad * 2) / (b.y1 - b.y0 || 1), maxK || 1.1);
      this.view.k = Math.max(0.05, k);
      this.view.x = (r.width - (b.x1 - b.x0) * this.view.k) / 2 - b.x0 * this.view.k;
      this.view.y = (r.height - (b.y1 - b.y0) * this.view.k) / 2 - b.y0 * this.view.k;
      this.applyTransform();
    }

    centerOn(id) {
      const n = this.nodes.get(id);
      if (!n) return;
      const r = this.svg.getBoundingClientRect();
      this.view.k = Math.max(this.view.k, 0.8);
      this.view.x = r.width / 2 - (n.x + n.w / 2) * this.view.k;
      this.view.y = r.height / 2 - (n.y + Math.min(n.h, 200) / 2) * this.view.k;
      this.applyTransform();
    }

    bindPanZoom() {
      let pan = null;
      this.svg.addEventListener('pointerdown', (ev) => {
        if (ev.target.closest('.node')) return;
        pan = { x: ev.clientX, y: ev.clientY, vx: this.view.x, vy: this.view.y, moved: false };
        this.svg.setPointerCapture(ev.pointerId);
        this.svg.classList.add('panning');
      });
      this.svg.addEventListener('pointermove', (ev) => {
        if (!pan) return;
        const dx = ev.clientX - pan.x, dy = ev.clientY - pan.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) pan.moved = true;
        this.view.x = pan.vx + dx; this.view.y = pan.vy + dy;
        this.applyTransform();
      });
      const end = () => {
        if (pan && !pan.moved) this.select(null);
        pan = null; this.svg.classList.remove('panning');
      };
      this.svg.addEventListener('pointerup', end);
      this.svg.addEventListener('pointercancel', () => { pan = null; this.svg.classList.remove('panning'); });
      this.svg.addEventListener('wheel', (ev) => {
        ev.preventDefault();
        const r = this.svg.getBoundingClientRect();
        this.zoomBy(Math.exp(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.0015)), ev.clientX - r.left, ev.clientY - r.top);
      }, { passive: false });
    }

    bindNode(g, n) {
      let drag = null;
      g.addEventListener('pointerdown', (ev) => {
        ev.stopPropagation();
        drag = { x: ev.clientX, y: ev.clientY, nx: n.x, ny: n.y, moved: false };
        g.setPointerCapture(ev.pointerId);
      });
      g.addEventListener('pointermove', (ev) => {
        if (!drag) return;
        const dx = (ev.clientX - drag.x) / this.view.k, dy = (ev.clientY - drag.y) / this.view.k;
        if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
        if (!drag.moved) return;
        n.x = drag.nx + dx; n.y = drag.ny + dy;
        this.positions.set(n.id, { x: n.x, y: n.y });
        g.setAttribute('transform', `translate(${n.x},${n.y})`);
        if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = null; this.drawEdges(); this.applyHighlight(); });
      });
      g.addEventListener('pointerup', () => {
        if (drag && !drag.moved) this.select(n.id);
        drag = null;
      });
      g.addEventListener('dblclick', (ev) => {
        ev.stopPropagation();
        if (n.ghost) location.href = classHref(n.id);
        else { this.select(n.id); this.centerOn(n.id); }
      });
    }

    select(id, center) {
      this.selected = id && this.nodes.has(id) ? id : null;
      this.applyHighlight();
      if (center && this.selected) this.centerOn(this.selected);
      if (this.config.onSelect) this.config.onSelect(this.selected);
    }

    setSearch(term) {
      this.search = term ? term.toLowerCase() : '';
      this.applyHighlight();
      if (!this.search) return [];
      return [...this.nodes.values()].filter((n) => n.cls.name.toLowerCase().includes(this.search)).map((n) => n.id);
    }

    applyHighlight() {
      if (!this.nodeEls) return;
      let focus = null;
      if (this.selected) {
        focus = new Set([this.selected]);
        for (const e of this.edges) {
          if (e.source === this.selected) focus.add(e.target);
          if (e.target === this.selected) focus.add(e.source);
        }
      } else if (this.highlightPatterns.size) {
        focus = new Set();
        for (const n of this.nodes.values()) if ((n.cls.patterns || []).some((p) => this.highlightPatterns.has(p.key))) focus.add(n.id);
      } else if (this.search) {
        focus = new Set([...this.nodes.values()].filter((n) => n.cls.name.toLowerCase().includes(this.search)).map((n) => n.id));
      }
      this.root.classList.toggle('dimmed', !!focus);
      for (const [id, g] of this.nodeEls) {
        g.classList.toggle('dim', !!focus && !focus.has(id));
        g.classList.toggle('selected', id === this.selected);
        g.classList.toggle('match', !!this.search && !this.selected && CLASSES[id].name.toLowerCase().includes(this.search));
      }
      for (const grp of this.edgeEls) {
        const a = grp.dataset.s, b = grp.dataset.t;
        const hl = this.selected ? (a === this.selected || b === this.selected) : false;
        grp.classList.toggle('dim', !!focus && !(focus.has(a) && focus.has(b) && (!this.selected || hl)));
        grp.classList.toggle('hl', hl);
        const line = grp.querySelector('path.line');
        line.setAttribute('marker-end', `url(#${this.uid}-${line.dataset.marker}${hl ? '-hl' : ''})`);
      }
    }

    exportSvg() {
      const clone = this.svg.cloneNode(true);
      const b = this.bbox();
      const pad = 20;
      clone.setAttribute('xmlns', SVGNS);
      clone.setAttribute('viewBox', `${b.x0 - pad} ${b.y0 - pad} ${b.x1 - b.x0 + pad * 2} ${b.y1 - b.y0 + pad * 2}`);
      clone.setAttribute('width', b.x1 - b.x0 + pad * 2);
      clone.setAttribute('height', b.y1 - b.y0 + pad * 2);
      clone.querySelector('g').removeAttribute('transform');
      clone.querySelector('g').classList.remove('dimmed');
      // inline computed styles so the file renders anywhere
      const src = this.svg.querySelectorAll('*'), dst = clone.querySelectorAll('*');
      const props = ['fill', 'fill-opacity', 'stroke', 'stroke-width', 'stroke-dasharray', 'font-family', 'font-size', 'font-weight', 'font-style', 'text-decoration', 'opacity', 'paint-order'];
      src.forEach((el, i) => {
        const cs = getComputedStyle(el);
        dst[i].setAttribute('style', props.map((p) => `${p}:${cs.getPropertyValue(p)}`).join(';'));
      });
      const bg = s('rect', { x: b.x0 - pad, y: b.y0 - pad, width: '100%', height: '100%', fill: getComputedStyle(document.body).backgroundColor });
      bg.setAttribute('width', b.x1 - b.x0 + pad * 2); bg.setAttribute('height', b.y1 - b.y0 + pad * 2);
      clone.insertBefore(bg, clone.firstChild.nextSibling);
      const blob = new Blob([new XMLSerializer().serializeToString(clone)], { type: 'image/svg+xml' });
      const a = h('a', { href: URL.createObjectURL(blob), download: `${(PAGE_MODULE || M.meta.title).replace(/[^\w.-]+/g, '_')}-classes.svg` });
      document.body.append(a); a.click(); a.remove();
    }
  }

  // ------------------------------------------------------------------ details panel
  function relationsOf(id) {
    const out = [], inc = [];
    for (const r of M.relations) {
      if (r.source === id) out.push(r);
      if (r.target === id && r.source !== id) inc.push(r);
    }
    return { out, inc };
  }

  function classLink(id, onPick) {
    const c = CLASSES[id];
    return h('a', {
      href: classHref(id), title: id,
      onclick: onPick ? (ev) => { if (onPick(id)) ev.preventDefault(); } : null,
    }, c.qualname);
  }

  function renderDetails(panel, id, onPick, onClose) {
    panel.innerHTML = '';
    if (!id) {
      panel.append(h('h3', {}, 'Details'), h('p', { class: 'hint' },
        'Click a class to see its attributes, methods, relations and detected patterns. Drag boxes to rearrange, scroll to zoom, drag the background to pan, double-click to focus.'));
      return;
    }
    const c = CLASSES[id];
    const mt = c.metrics;
    panel.append(...[
      h('div', { class: 'close' }, onClose ? iconBtn('close', 'Close details', onClose) : null),
      h('div', { class: 'stereo' }, stereotypes(c).map((x) => `«${x}»`).join(' ')),
      h('h2', {}, c.qualname),
      h('div', { class: 'where' }, `${c.module} · ${c.file}:${c.lineno}`),
      c.docstring ? h('p', { class: 'doc' }, c.docstring) : null,
      h('h3', {}, 'Metrics'),
      h('div', { class: 'metrics' },
        [['dit', 'Depth'], ['noc', 'Children'], ['fan_in', 'Fan-in'], ['fan_out', 'Fan-out']].map(([k, l]) =>
          h('div', { title: { dit: 'Depth of inheritance tree', noc: 'Number of direct subclasses', fan_in: 'Classes depending on this one', fan_out: 'Classes this one depends on' }[k] }, h('b', {}, mt[k]), h('span', {}, l)))),
    ].filter(Boolean));
    if (c.patterns.length) {
      panel.append(h('h3', {}, 'Design patterns'));
      for (const p of c.patterns) {
        const match = M.patterns[p.match];
        panel.append(h('div', { class: 'pat-block', style: { borderLeftColor: color(p.key) } },
          h('b', {}, CAT[p.key].name), ' ', h('span', { class: 'stereo' }, `as ${p.role} · ${Math.round(p.confidence * 100)}%`),
          h('ul', {}, match.evidence.map((e) => h('li', {}, e))),
          h('div', { class: 'chips' }, match.participants.filter((x) => x.id !== id).slice(0, 12).map((x) =>
            h('span', { class: 'chip role' }, classLink(x.id, onPick), ' · ', x.role)))));
      }
    }
    const bases = c.bases.map((b, i) => c.base_ids[i] ? classLink(c.base_ids[i], onPick) : h('code', {}, b));
    if (bases.length || c.subclasses.length) {
      panel.append(h('h3', {}, 'Hierarchy'), h('ul', { class: 'rel-list' },
        bases.length ? h('li', {}, h('span', { class: 'k' }, 'extends'), bases.flatMap((b, i) => i ? [', ', b] : [b])) : null,
        c.subclasses.length ? h('li', {}, h('span', { class: 'k' }, 'subclasses'), c.subclasses.flatMap((b, i) => i ? [', ', classLink(b, onPick)] : [classLink(b, onPick)])) : null,
        c.metaclass ? h('li', {}, h('span', { class: 'k' }, 'metaclass'), h('code', {}, c.metaclass)) : null));
    }
    const attrs = c.attributes;
    panel.append(h('h3', {}, `Attributes (${attrs.length})`));
    panel.append(attrs.length ? h('div', { class: 'table-wrap' }, h('table', {},
      h('tr', {}, h('th', {}, ''), h('th', {}, 'Name'), h('th', {}, 'Type'), h('th', {}, 'Kind')),
      attrs.map((a) => h('tr', {},
        h('td', { title: a.visibility }, h('code', {}, VIS[a.visibility])),
        h('td', {}, h('code', {}, a.name), a.default ? h('div', { class: 'hint' }, '= ' + a.default) : null),
        h('td', {}, a.type ? h('code', {}, a.type) : h('span', { class: 'hint' }, '—')),
        h('td', { class: 'hint' }, [a.kind === 'field' ? a.scope : a.kind.replace('_', ' '), a.origin !== 'unknown' && a.origin !== 'literal' ? a.origin : null, a.kind === 'property' && !a.readonly ? 'settable' : null].filter(Boolean).join(', ')))))) : h('p', { class: 'empty' }, 'None'));
    panel.append(h('h3', {}, `Methods (${c.methods.length})`));
    panel.append(c.methods.length ? h('div', { class: 'table-wrap' }, h('table', {},
      c.methods.map((m) => h('tr', {},
        h('td', { title: m.visibility }, h('code', {}, VIS[m.visibility])),
        h('td', {},
          h('code', { style: { fontStyle: m.is_abstract ? 'italic' : null } }, `${m.is_async ? 'async ' : ''}${m.name}(${m.params.map((p) => (p.kind === 'vararg' ? '*' : p.kind === 'kwarg' ? '**' : '') + p.name + (p.annotation ? ': ' + p.annotation : '') + (p.default ? ' = ' + p.default : '')).join(', ')})${m.returns ? ' → ' + m.returns : ''}`),
          m.decorators.length ? h('div', { class: 'hint' }, m.decorators.map((d) => '@' + d).join(' ')) : null,
          m.docstring ? h('div', { class: 'hint' }, m.docstring) : null))))) : h('p', { class: 'empty' }, 'None'));
    const { out, inc } = relationsOf(id);
    const relItems = [
      ...out.map((r) => h('li', {}, h('span', { class: 'k' }, r.kind === 'inheritance' ? 'extends' : r.kind === 'realization' ? 'implements' : r.kind === 'composition' ? 'owns' : r.kind === 'aggregation' ? 'has' : 'uses'),
        classLink(r.target, onPick), r.label ? h('span', { class: 'hint' }, ` via ${r.label}${r.multiplicity && r.multiplicity !== '1' ? ' [' + multLabel(r.multiplicity) + ']' : ''}`) : null)),
      ...inc.map((r) => h('li', {}, h('span', { class: 'k' }, r.kind === 'inheritance' ? 'extended by' : r.kind === 'realization' ? 'implemented by' : r.kind === 'composition' ? 'owned by' : r.kind === 'aggregation' ? 'held by' : 'used by'),
        classLink(r.source, onPick))),
    ];
    panel.append(h('h3', {}, `Relations (${relItems.length})`), relItems.length ? h('ul', { class: 'rel-list' }, relItems) : h('p', { class: 'empty' }, 'None'));
  }

  // ------------------------------------------------------------------ diagram page
  function relLegendSample(kind) {
    const svg = s('svg', { width: 54, height: 14, viewBox: '0 0 54 14' });
    const uid = 'lg-' + kind;
    const d = s('defs', {}, svg);
    const m = s('marker', { id: uid, viewBox: '0 0 18 14', refX: 13, refY: 7, markerWidth: 18, markerHeight: 14, markerUnits: 'userSpaceOnUse', orient: 'auto' }, d);
    const path = { inheritance: 'M1,1 L13,7 L1,13 Z', realization: 'M1,1 L13,7 L1,13 Z', composition: 'M-3,7 L5,2 L13,7 L5,12 Z', aggregation: 'M-3,7 L5,2 L13,7 L5,12 Z', dependency: 'M3,2 L13,7 L3,12' }[kind];
    s('path', { d: path, class: { inheritance: 'marker-hollow', realization: 'marker-hollow', composition: 'marker-filled', aggregation: 'marker-hollow', dependency: 'marker-open' }[kind] }, m);
    const g = s('g', { class: 'edge ' + kind }, svg);
    s('path', { class: 'line', d: 'M2,7 H40', 'marker-end': `url(#${uid})` }, g);
    return svg;
  }

  function pickerPage(app, kind) {
    const items = kind === 'package' ? PACKAGES.map((p) => [p.name, p.classes]) : M.modules.filter((m) => m.classes.length).map((m) => [m.name, m.classes.length]);
    const page = h('main', { class: 'page' }, h('h1', {}, kind === 'package' ? 'Packages' : 'Modules'),
      h('p', { class: 'subtitle' }, PAGE_MODULE ? `“${PAGE_MODULE}” is not in this report. Pick one below.` : `Pick a ${kind} to open its class diagram.`),
      h('div', { class: 'panel table-wrap' }, h('table', {}, h('tr', {}, h('th', {}, 'Name'), h('th', { class: 'num' }, 'Classes')),
        items.map(([n, c]) => h('tr', {}, h('td', {}, h('a', { class: 'mono', href: pageHref(kind, n) }, n)), h('td', { class: 'num' }, c))))));
    app.append(page);
    window.addEventListener('hashchange', () => location.reload());
  }

  function diagramPage(app) {
    const isPackage = PAGE === 'package';
    const isModule = PAGE === 'module' || isPackage;  // both show a subset plus neighbouring context
    const mod = PAGE === 'module' ? M.modules.find((m) => m.name === PAGE_MODULE)
      : isPackage && PACKAGES.some((p) => p.name === PAGE_MODULE) ? { ...PACKAGES.find((p) => p.name === PAGE_MODULE), docstring: (M.modules.find((m) => m.name === PAGE_MODULE) || {}).docstring } : null;
    if (isModule && !mod) { pickerPage(app, PAGE); return; }
    if (isModule) document.title = `${PAGE_MODULE} · ${M.meta.title}`;
    const inPackage = (name) => name === PAGE_MODULE || name.startsWith(PAGE_MODULE + '.');
    const pkgIds = isPackage ? Object.keys(CLASSES).filter((id) => inPackage(CLASSES[id].module)) : null;
    const big = (pkgIds || (PAGE === 'module' ? [] : Object.keys(CLASSES))).length > 80;
    const key = 'archlens-opts-' + PAGE;
    const saved = store.get(key, {});
    const opt = {
      attributes: saved.attributes ?? true,
      methods: saved.methods ?? !big,
      specialMethods: saved.specialMethods ?? false,
      privateMembers: saved.privateMembers ?? true,
      labels: saved.labels ?? true,
      context: isModule ? (saved.context ?? true) : false,
      contextDependencies: false,
      dependencyLayers: saved.dependencyLayers ?? false,
      relations: new Set(saved.relations || (big ? ['inheritance', 'realization', 'composition', 'aggregation'] : RELS)),
    };
    const save = () => store.set(key, { ...opt, relations: [...opt.relations] });
    const hiddenModules = new Set(PAGE === 'module' ? [] : store.get('archlens-hidden-modules-' + (PAGE_MODULE || '*'), []));
    const ids = () => PAGE === 'module' ? mod.classes
      : (pkgIds || Object.keys(CLASSES)).filter((id) => !hiddenModules.has(CLASSES[id].module));

    const sidebar = h('aside', { class: 'sidebar' });
    const canvas = h('div', { class: 'canvas' });
    const details = h('aside', { class: 'details' });
    const ws = h('div', { class: 'workspace' }, sidebar, canvas, details);
    app.append(ws);

    let diagram;
    const pick = (id) => {
      if (diagram.nodes.has(id) && !diagram.nodes.get(id).ghost) { diagram.select(id, true); return true; }
      return false;
    };
    const onSelect = (id) => {
      renderDetails(details, id, pick, id ? () => diagram.select(null) : null);
      const base = isModule ? `#m=${encodeURIComponent(PAGE_MODULE)}` : '';
      if (id) history.replaceState(null, '', withParam(base || location.pathname, 'class', id).replace(location.pathname, ''));
      else if (hashParams().has('class')) history.replaceState(null, '', base || location.pathname + location.search);
    };

    // sidebar content
    const search = h('input', { type: 'search', placeholder: 'Search classes…', 'aria-label': 'Search classes' });
    search.addEventListener('input', () => diagram.setSearch(search.value.trim()));
    search.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter') { const hits = diagram.setSearch(search.value.trim()); if (hits.length) diagram.select(hits[0], true); }
      if (ev.key === 'Escape') { search.value = ''; diagram.setSearch(''); }
    });
    const check = (label, prop, after) => h('label', { class: 'opt' },
      h('input', { type: 'checkbox', checked: opt[prop] ? true : null, onchange: (e) => { opt[prop] = e.target.checked; save(); after(); } }), label);
    const rerender = () => diagram.refresh(false);
    const relayout = () => diagram.refresh(true);

    sidebar.append(...[
      isModule ? h('div', {}, h('h3', {}, isPackage ? `Package · ${mod.classes} classes` : 'Module'), h('div', { class: 'mono', style: { wordBreak: 'break-all' } }, mod.name),
        mod.docstring ? h('p', { class: 'hint' }, mod.docstring.split('\n')[0]) : null) : null,
      h('h3', {}, 'Find'), search,
      h('h3', {}, 'Show'),
      check('Attributes', 'attributes', relayout), check('Methods', 'methods', relayout),
      check('Private & protected members', 'privateMembers', relayout), check('Special (dunder) methods', 'specialMethods', relayout),
      check('Relation labels', 'labels', rerender),
      isModule ? check(`Neighbours from other ${isPackage ? 'packages' : 'modules'}`, 'context', relayout) : null,
      check('Dependencies shape layout', 'dependencyLayers', relayout),
      h('h3', {}, 'Relations'),
      h('div', { class: 'rel-legend' }, RELS.flatMap((k) => [relLegendSample(k), h('label', { class: 'opt', title: REL_HELP[k] },
        h('input', { type: 'checkbox', checked: opt.relations.has(k) ? true : null, onchange: (e) => { if (e.target.checked) opt.relations.add(k); else opt.relations.delete(k); save(); relayout(); } }),
        REL_LABEL[k])])),
    ].filter(Boolean));
    const patSection = h('div', {});
    sidebar.append(h('h3', {}, 'Design patterns'), h('p', { class: 'hint', style: { margin: '0 0 6px' } }, 'Click to highlight participants.'), patSection);
    if (PAGE !== 'module' && M.modules.length > 1) {
      const mods = M.modules.filter((m) => m.classes.length && (!isPackage || inPackage(m.name)));
      const list = h('div', { class: 'module-list' }, mods.map((m) => h('label', { class: 'opt' },
        h('input', { type: 'checkbox', checked: hiddenModules.has(m.name) ? null : true, onchange: (e) => {
          if (e.target.checked) hiddenModules.delete(m.name); else hiddenModules.add(m.name);
          store.set('archlens-hidden-modules-' + (PAGE_MODULE || '*'), [...hiddenModules]); relayout(); renderPatternLegend();
        } }), h('span', { class: 'mono' }, m.name), h('span', { class: 'hint' }, ` ${m.classes.length}`))));
      sidebar.append(h('h3', {}, 'Modules'), list);
    }

    function renderPatternLegend() {
      patSection.innerHTML = '';
      const counts = {};
      for (const id of ids()) for (const p of new Set((CLASSES[id].patterns || []).map((p) => p.key))) counts[p] = (counts[p] || 0) + 1;
      for (const cat of CATEGORIES) {
        const keys = Object.keys(CAT).filter((k) => CAT[k].category === cat && counts[k]);
        if (!keys.length) continue;
        patSection.append(h('div', { class: 'hint', style: { margin: '6px 0 2px' } }, CATEGORY_LABEL[cat]));
        for (const k of keys) {
          const btn = h('button', { class: 'legend-item' + (diagram.highlightPatterns.has(k) ? ' on' : ''), title: CAT[k].description, 'aria-pressed': diagram.highlightPatterns.has(k) ? 'true' : 'false',
            onclick: () => {
              if (diagram.highlightPatterns.has(k)) diagram.highlightPatterns.delete(k); else diagram.highlightPatterns.add(k);
              diagram.select(null); renderPatternLegend();
            } }, h('span', { class: 'sw', style: { background: CAT[k].color } }), CAT[k].name, h('span', { class: 'n' }, counts[k]));
          patSection.append(btn);
        }
      }
      if (!patSection.children.length) patSection.append(h('p', { class: 'empty' }, 'No patterns detected here.'));
    }

    diagram = new Diagram(canvas, { ids, options: opt, onSelect });
    renderPatternLegend();
    renderDetails(details, null);

    const fromHash = () => {
      const hp = hashParams();
      if (isModule && (hp.get('m') || '') !== PAGE_MODULE && !document.body.dataset.module) { location.reload(); return; }
      if (hp.has('class')) { const id = hp.get('class'); setTimeout(() => diagram.select(id, true), 50); }
      if (hp.has('pattern')) { diagram.highlightPatterns = new Set(hp.get('pattern').split(',')); diagram.applyHighlight(); renderPatternLegend(); }
    };
    fromHash();
    window.addEventListener('hashchange', fromHash);
    document.addEventListener('keydown', (ev) => {
      if (ev.target.tagName === 'INPUT') return;
      if (ev.key === '/') { ev.preventDefault(); search.focus(); }
      if (ev.key === 'Escape') { diagram.highlightPatterns.clear(); diagram.select(null); renderPatternLegend(); }
      if (ev.key === 'f') diagram.fit();
    });
  }

  // ------------------------------------------------------------------ overview page
  function overviewPage(app) {
    const page = h('main', { class: 'page' });
    app.append(page);
    const cls = Object.values(CLASSES);
    const count = (f) => cls.filter(f).length;
    page.append(
      h('h1', {}, M.meta.title),
      h('p', { class: 'subtitle' }, `Architecture review generated by ArchLens ${M.meta.version} on ${M.meta.generated}`),
      h('div', { class: 'cards' }, [
        [M.modules.length, 'Modules'], [cls.length, 'Classes'],
        [M.relations.filter((r) => r.kind === 'inheritance' || r.kind === 'realization').length, 'Inheritance links'],
        [M.relations.filter((r) => r.kind === 'composition' || r.kind === 'aggregation').length, 'Composition / aggregation'],
        [M.patterns.filter((p) => CAT[p.key].category !== 'idiom').length, 'Design pattern instances'],
        [count((c) => c.is_abstract), 'Abstract classes / protocols'],
      ].map(([v, l]) => h('div', { class: 'card' }, h('div', { class: 'value' }, v), h('div', { class: 'label' }, l)))));

    // pattern distribution
    const counts = {};
    for (const p of M.patterns) counts[p.key] = (counts[p.key] || 0) + 1;
    const max = Math.max(1, ...Object.values(counts));
    const bars = h('div', { class: 'bars', role: 'table', 'aria-label': 'Detected pattern instances by pattern' });
    for (const cat of CATEGORIES) {
      const keys = Object.keys(CAT).filter((k) => CAT[k].category === cat && counts[k]).sort((a, b) => counts[b] - counts[a]);
      if (!keys.length) continue;
      bars.append(h('div', { class: 'cat' }, CATEGORY_LABEL[cat]));
      for (const k of keys) {
        bars.append(
          h('a', { class: 'name', href: `patterns.html#${k}`, title: CAT[k].description }, CAT[k].name),
          h('div', { class: 'track', title: `${CAT[k].name}: ${counts[k]} instance${counts[k] > 1 ? 's' : ''}` },
            h('div', { class: 'bar', style: { width: `${(counts[k] / max) * 100}%`, background: CAT[k].color } })),
          h('div', { class: 'count' }, counts[k]));
      }
    }
    if (!M.patterns.length) bars.append(h('p', { class: 'empty' }, 'No patterns detected.'));

    // hotspots
    const top = [...cls].sort((a, b) => (b.metrics.fan_in + b.metrics.fan_out) - (a.metrics.fan_in + a.metrics.fan_out)).slice(0, 10);
    const hot = h('div', { class: 'table-wrap' }, h('table', {},
      h('tr', {}, h('th', {}, 'Class'), h('th', { class: 'num', title: 'incoming relations' }, 'In'), h('th', { class: 'num', title: 'outgoing relations' }, 'Out'),
        h('th', { class: 'num', title: 'depth of inheritance' }, 'DIT'), h('th', { class: 'num', title: 'methods' }, 'Meth.')),
      top.map((c) => h('tr', {}, h('td', {}, h('a', { href: classHref(c.id), class: 'mono' }, c.qualname), h('div', { class: 'hint' }, c.module)),
        h('td', { class: 'num' }, c.metrics.fan_in), h('td', { class: 'num' }, c.metrics.fan_out), h('td', { class: 'num' }, c.metrics.dit), h('td', { class: 'num' }, c.metrics.methods)))));

    page.append(h('div', { class: 'two-col', style: { marginTop: '24px' } },
      h('section', { class: 'panel' }, h('h2', { style: { marginTop: 0 } }, 'Detected patterns'), bars),
      h('section', { class: 'panel' }, h('h2', { style: { marginTop: 0 } }, 'Most connected classes'), top.length ? hot : h('p', { class: 'empty' }, 'No classes found.'))));

    const patternChips = (ids, href) => {
      const keys = new Set();
      ids.forEach((id) => CLASSES[id].patterns.forEach((p) => { if (!_isSupport(p) && CAT[p.key].category !== 'idiom') keys.add(p.key); }));
      return h('div', { class: 'chips' }, [...keys].map((k) => chip(k, null, withParam(href, 'pattern', k))));
    };
    if (PACKAGES.length) {
      page.append(h('h2', {}, `Packages (${PACKAGES.length})`), h('div', { class: 'panel table-wrap' }, h('table', {},
        h('tr', {}, h('th', {}, 'Package'), h('th', { class: 'num' }, 'Modules'), h('th', { class: 'num' }, 'Classes'), h('th', {}, 'Patterns')),
        PACKAGES.map((p) => {
          const ids = Object.keys(CLASSES).filter((id) => CLASSES[id].module === p.name || CLASSES[id].module.startsWith(p.name + '.'));
          const depth = p.name.split('.').length - PACKAGES[0].name.split('.').length;
          return h('tr', {},
            h('td', {}, h('a', { href: pageHref('package', p.name), class: 'mono', style: { paddingLeft: `${Math.max(0, depth) * 14}px` } }, p.name),
              p.docstring ? h('div', { class: 'hint', style: { paddingLeft: `${Math.max(0, depth) * 14}px` } }, p.docstring.split('\n')[0]) : null),
            h('td', { class: 'num' }, p.modules), h('td', { class: 'num' }, p.classes),
            h('td', {}, patternChips(ids, pageHref('package', p.name))));
        }))));
    }
    const classModules = M.modules.filter((m) => m.classes.length);
    page.append(h('h2', {}, `Modules with classes (${classModules.length})`), h('div', { class: 'panel table-wrap' }, h('table', {},
      h('tr', {}, h('th', {}, 'Module'), h('th', { class: 'num' }, 'Classes'), h('th', { class: 'num' }, 'Functions'), h('th', {}, 'Patterns')),
      classModules.map((m) => {
        const keys = new Set();
        m.classes.forEach((id) => CLASSES[id].patterns.forEach((p) => { if (!_isSupport(p)) keys.add(p.key); }));
        return h('tr', {},
          h('td', {}, h('a', { href: pageHref('module', m.name), class: 'mono' }, m.name), m.docstring ? h('div', { class: 'hint' }, m.docstring.split('\n')[0]) : null),
          h('td', { class: 'num' }, m.classes.length), h('td', { class: 'num' }, m.functions.length),
          h('td', {}, h('div', { class: 'chips' }, [...keys].map((k) => chip(k, null, withParam(pageHref('module', m.name), 'pattern', k))))));
      }))));

    if (M.warnings.length) {
      page.append(h('h2', {}, `Warnings (${M.warnings.length})`), h('ul', { class: 'warning-list' }, M.warnings.map((w) => h('li', {}, w))));
    }
  }


  // ------------------------------------------------------------------ patterns page
  function patternsPage(app) {
    const page = h('main', { class: 'page' });
    app.append(page);
    page.append(h('h1', {}, 'Design patterns'),
      h('p', { class: 'subtitle' }, 'Detected heuristically from class structure and method bodies. Each instance lists its participants, the evidence found and a confidence score. Colours match the class diagrams.'));
    let minConf = store.get('archlens-minconf', 0);
    const body = h('div', {});
    const sel = h('select', { 'aria-label': 'Minimum confidence', onchange: (e) => { minConf = +e.target.value; store.set('archlens-minconf', minConf); draw(); } },
      [[0, 'All confidence levels'], [0.6, '≥ 60% confidence'], [0.75, '≥ 75% confidence'], [0.9, '≥ 90% confidence']].map(([v, l]) => h('option', { value: v, selected: v === minConf ? true : null }, l)));
    let showIdioms = store.get('archlens-idioms', true);
    const idioms = h('label', { class: 'opt' }, h('input', { type: 'checkbox', checked: showIdioms ? true : null, onchange: (e) => { showIdioms = e.target.checked; store.set('archlens-idioms', showIdioms); draw(); } }), 'Include Python idioms');
    page.append(h('div', { class: 'filters' }, sel, idioms), body);

    function draw() {
      body.innerHTML = '';
      let any = false;
      for (const cat of CATEGORIES) {
        if (cat === 'idiom' && !showIdioms) continue;
        const keys = Object.keys(CAT).filter((k) => CAT[k].category === cat);
        const cards = [];
        for (const k of keys) {
          const inst = M.patterns.map((p, i) => [p, i]).filter(([p]) => p.key === k && p.confidence >= minConf);
          if (!inst.length) continue;
          const card = h('section', { class: 'pattern-card', id: k },
            h('header', { style: { borderLeftColor: CAT[k].color } },
              h('div', {}, h('h3', {}, CAT[k].name), h('p', {}, CAT[k].description)),
              h('span', { class: 'count' }, `${inst.length} instance${inst.length > 1 ? 's' : ''}`)));
          for (const [p] of inst) {
            const mini = h('div', { class: 'mini', hidden: true });
            let built = null;
            const toggle = h('button', { class: 'btn', onclick: () => {
              mini.hidden = !mini.hidden;
              toggle.textContent = mini.hidden ? 'Show diagram' : 'Hide diagram';
              if (!mini.hidden && !built) {
                built = new Diagram(mini, {
                  ids: () => p.participants.map((x) => x.id), compact: true,
                  options: { attributes: true, methods: true, specialMethods: false, privateMembers: true, labels: true, context: false, relations: new Set(RELS), dependencyLayers: false },
                });
                built.highlightPatterns = new Set([k]);
                built.applyHighlight();
              }
            } }, 'Show diagram');
            card.append(h('div', { class: 'instance' },
              h('div', { class: 'chips' }, p.participants.map((x) => h('span', { class: 'chip' }, h('i', { style: { background: _isSupport(x) ? 'transparent' : CAT[k].color, border: `1.5px solid ${CAT[k].color}` } }),
                h('a', { href: classHref(x.id), class: 'mono' }, CLASSES[x.id].qualname), h('span', { class: 'stereo' }, '· ' + x.role)))),
              h('ul', {}, p.evidence.map((e) => h('li', {}, e))),
              h('div', { style: { display: 'flex', gap: '12px', alignItems: 'center' } },
                h('span', { class: 'conf', title: 'Heuristic confidence' }, 'confidence', h('span', { class: 'meter' }, h('span', { style: { width: `${p.confidence * 100}%` } })), `${Math.round(p.confidence * 100)}%`),
                toggle),
              mini));
          }
          cards.push(card);
        }
        if (cards.length) { any = true; body.append(h('h2', {}, CATEGORY_LABEL[cat]), ...cards); }
      }
      if (!any) body.append(h('p', { class: 'empty' }, 'No patterns match the current filters.'));
      if (location.hash) { const el = document.getElementById(location.hash.slice(1)); if (el) el.scrollIntoView(); }
    }
    draw();
  }

  // ------------------------------------------------------------------ boot
  const app = document.getElementById('app');
  app.append(topbar());
  if (PAGE === 'overview') overviewPage(app);
  else if (PAGE === 'patterns') patternsPage(app);
  else diagramPage(app);
  window.ArchLens = { Diagram, layout, model: M };
})();
