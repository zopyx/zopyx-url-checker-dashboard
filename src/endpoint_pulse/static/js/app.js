/* Basic client for folder/node tree and URL testing */

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const text = await res.text();
  try { return JSON.parse(text); } catch { return text; }
}

function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  Object.entries(attrs).forEach(([k, v]) => {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.substring(2), v);
    else if (k === 'html') e.innerHTML = v;
    else e.setAttribute(k, v);
  });
  for (const c of children) {
    if (c == null) continue;
    if (typeof c === 'string') e.appendChild(document.createTextNode(c));
    else e.appendChild(c);
  }
  return e;
}

async function loadTree() {
  const data = await api('/api/tree');
  const tree = document.getElementById('tree');
  tree.innerHTML = '';

  if (!data.folders || data.folders.length === 0) {
    tree.appendChild(el('div', { class: 'text-muted small' }, 'No folders yet. Click "Add Folder" to create one.'));
    return;
  }

  data.folders.forEach(folder => {
    const folderHeader = el('div', { class: 'd-flex align-items-center justify-content-between folder-header' },
      el('div', { class: 'd-flex align-items-center gap-2' },
        el('button', { class: 'btn btn-sm btn-outline-primary', onclick: () => toggleFolder(folder.id) }, '▸'),
        el('strong', {}, folder.name),
      ),
      el('div', { class: 'btn-group btn-group-sm' },
        el('button', { class: 'btn btn-outline-success', onclick: () => addNode(folder.id) }, 'Add Node'),
        el('button', { class: 'btn btn-outline-secondary', onclick: () => renameFolder(folder.id, folder.name) }, 'Rename'),
        el('button', { class: 'btn btn-outline-danger', onclick: () => deleteFolder(folder.id) }, 'Delete'),
      ),
    );

    const nodesList = el('div', { id: `folder-${folder.id}-nodes`, class: 'ms-4 mt-2', style: 'display:none' });
    if (folder.nodes && folder.nodes.length > 0) {
      folder.nodes.forEach(node => nodesList.appendChild(renderNode(node)));
    } else {
      nodesList.appendChild(el('div', { class: 'text-muted small' }, 'No nodes in this folder.'));
    }

    tree.appendChild(el('div', { class: 'mb-3' }, folderHeader, nodesList));
  });
}

function renderNode(node) {
  const badge = node.active
    ? el('span', { class: 'badge bg-success' }, 'active')
    : el('span', { class: 'badge bg-secondary' }, 'inactive');

  return el('div', { class: 'd-flex align-items-center justify-content-between node-item py-1' },
    el('div', {},
      el('div', { class: 'fw-semibold' }, node.name, ' ', badge),
      el('div', { class: 'small text-muted' }, node.url, node.comment ? ` – ${node.comment}` : ''),
    ),
    el('div', { class: 'btn-group btn-group-sm' },
      el('button', { class: 'btn btn-outline-primary', onclick: () => testNode(node.id) }, 'Test'),
      el('button', { class: 'btn btn-outline-secondary', onclick: () => editNode(node) }, 'Edit'),
      el('button', { class: 'btn btn-outline-danger', onclick: () => deleteNode(node.id) }, 'Delete'),
    )
  );
}

function toggleFolder(id) {
  const eln = document.getElementById(`folder-${id}-nodes`);
  if (!eln) return;
  eln.style.display = (eln.style.display === 'none') ? 'block' : 'none';
}

async function addFolder() {
  const name = prompt('Folder name:');
  if (!name) return;
  try {
    await api('/api/folders', { method: 'POST', body: JSON.stringify({ name }) });
    await loadTree();
  } catch (e) { alert(e.message); }
}

async function renameFolder(id, currentName) {
  const name = prompt('New folder name:', currentName || '');
  if (!name) return;
  try {
    await api(`/api/folders/${id}`, { method: 'PUT', body: JSON.stringify({ name }) });
    await loadTree();
  } catch (e) { alert(e.message); }
}

async function deleteFolder(id) {
  if (!confirm('Delete folder and all its nodes?')) return;
  try {
    await api(`/api/folders/${id}`, { method: 'DELETE' });
    await loadTree();
  } catch (e) { alert(e.message); }
}

async function addNode(folder_id) {
  const name = prompt('Node name:');
  if (!name) return;
  const url = prompt('URL (include http/https):');
  if (!url) return;
  const comment = prompt('Comment (optional):') || '';
  const activeStr = prompt('Active? (y/n)', 'y') || 'y';
  const active = activeStr.toLowerCase().startsWith('y');
  try {
    await api(`/api/folders/${folder_id}/nodes`, { method: 'POST', body: JSON.stringify({ name, url, comment, active }) });
    await loadTree();
  } catch (e) { alert(e.message); }
}

async function editNode(node) {
  const name = prompt('Node name:', node.name);
  if (!name) return;
  const url = prompt('URL:', node.url);
  if (!url) return;
  const comment = prompt('Comment:', node.comment || '') || '';
  const activeStr = prompt('Active? (y/n)', node.active ? 'y' : 'n') || 'y';
  const active = activeStr.toLowerCase().startsWith('y');
  try {
    await api(`/api/nodes/${node.id}`, { method: 'PUT', body: JSON.stringify({ name, url, comment, active }) });
    await loadTree();
  } catch (e) { alert(e.message); }
}

async function deleteNode(id) {
  if (!confirm('Delete node?')) return;
  try {
    await api(`/api/nodes/${id}`, { method: 'DELETE' });
    await loadTree();
  } catch (e) { alert(e.message); }
}

async function testNode(id) {
  try {
    const res = await api(`/api/nodes/${id}/test`, { method: 'POST' });
    const details = document.getElementById('details');
    if (res.tested === false && res.reason) {
      details.innerText = `Node ${id}: ${res.reason}`;
      return;
    }
    if (res.ok) {
      details.innerText = `OK ${res.status_code} in ${res.elapsed_ms}ms — ${res.url}`;
    } else if ('status_code' in res) {
      details.innerText = `FAIL ${res.status_code} in ${res.elapsed_ms}ms — ${res.url}`;
    } else {
      details.innerText = `ERROR in ${res.elapsed_ms}ms — ${res.url}: ${res.error}`;
    }
  } catch (e) { alert(e.message); }
}

function bindUI() {
  document.getElementById('addFolderBtn').addEventListener('click', addFolder);
  document.getElementById('refreshBtn').addEventListener('click', loadTree);
}

window.addEventListener('DOMContentLoaded', async () => {
  bindUI();
  await loadTree();
});
