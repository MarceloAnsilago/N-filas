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
  const isVideo = file =>
    file.type.startsWith('video/') || /\.(mp4|m4v|webm|ogv|mov|mkv|avi|mpeg|mpg)$/i.test(file.name);
  window.painelFolderSettings = { get, isVideo };

  const section = document.getElementById('admin-media-folder');
  if (!section) return;
  const unit = section.dataset.unit;
  const choose = document.getElementById('save-media-folder');
  const input = document.getElementById('admin-media-folder-input');
  const remove = document.getElementById('remove-media-folder');
  const status = document.getElementById('admin-media-folder-status');
  let useFileInput = !window.showDirectoryPicker;

  function show(folder) {
    remove.hidden = !folder;
    status.textContent = folder ? 'Pasta configurada neste navegador: ' + folder.name : '';
    if (folder?.videos) status.textContent += '. Se os vídeos mudarem, selecione a pasta novamente.';
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
      if (error.name !== 'AbortError') {
        status.textContent = error.name === 'QuotaExceededError'
          ? 'Espaço insuficiente no navegador. Escolha a pasta diretamente no painel.'
          : 'Não foi possível atualizar a pasta neste navegador. Você pode escolhê-la diretamente no painel.';
      }
    } finally {
      choose.disabled = false;
      remove.disabled = false;
    }
  }

  function save(folder) {
    return update(async () => {
      await access('readwrite', store => store.put(folder, unit));
      return folder;
    });
  }

  choose.addEventListener('click', async () => {
    if (useFileInput) {
      input.click();
      return;
    }
    try {
      await save(await window.showDirectoryPicker({ mode: 'read' }));
    } catch (error) {
      if (error.name !== 'AbortError') {
        useFileInput = true;
        status.textContent = 'Clique em Escolher pasta de vídeos novamente para usar o seletor alternativo.';
      }
    }
  });
  input.addEventListener('change', () => {
    const videos = Array.from(input.files).filter(isVideo)
      .map(file => ({ file, path: file.webkitRelativePath }));
    input.value = '';
    if (!videos.length) {
      status.textContent = 'Nenhum vídeo encontrado na pasta.';
      return;
    }
    save({ name: videos[0].path.split('/')[0], videos });
  });
  remove.addEventListener('click', () => update(async () => {
    await access('readwrite', store => store.delete(unit));
  }));
})();
