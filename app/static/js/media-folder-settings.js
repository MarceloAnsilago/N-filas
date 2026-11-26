(() => {
  async function access(mode, operation) {
    const db = await new Promise((resolve, reject) => {
      const request = indexedDB.open('painel-media', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('folders');
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction('folders', mode);
        const request = operation(transaction.objectStore('folders'));
        transaction.oncomplete = () => resolve(request.result);
        transaction.onabort = () => reject(transaction.error);
      });
    } finally {
      db.close();
    }
  }

  const get = unit => access('readonly', store => store.get(unit));
  window.painelFolderSettings = { get };

  const section = document.getElementById('admin-media-folder');
  if (!section) return;
  const unit = section.dataset.unit;
  const choose = document.getElementById('save-media-folder');
  const remove = document.getElementById('remove-media-folder');
  const status = document.getElementById('admin-media-folder-status');

  function show(folder) {
    remove.hidden = !folder;
    status.textContent = folder ? 'Pasta configurada neste navegador: ' + folder.name : '';
  }

  if (!window.showDirectoryPicker) {
    choose.disabled = true;
    status.textContent = 'Use o Edge ou o Chrome em HTTPS para configurar a pasta aqui. Também é possível escolher a pasta diretamente no painel.';
    return;
  }

  choose.disabled = true;
  get(unit).then(show).catch(() => {
    status.textContent = 'Não foi possível consultar a pasta configurada.';
  }).finally(() => { choose.disabled = false; });

  async function update(operation) {
    choose.disabled = true;
    remove.disabled = true;
    try {
      show(await operation());
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = 'Não foi possível atualizar a pasta neste navegador.';
    } finally {
      choose.disabled = false;
      remove.disabled = false;
    }
  }

  choose.addEventListener('click', () => update(async () => {
    const folder = await window.showDirectoryPicker({ mode: 'read' });
    await access('readwrite', store => store.put(folder, unit));
    return folder;
  }));
  remove.addEventListener('click', () => update(async () => {
    await access('readwrite', store => store.delete(unit));
  }));
})();
