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
  async function getSettings(unit) {
    const value = await get(unit);
    return value?.source ? value : { source: value ? 'folder' : 'youtube', folder: value };
  }
  window.painelFolderSettings = {
    async get(unit) {
      const settings = await getSettings(unit);
      return settings.source === 'folder' ? settings.folder : undefined;
    },
    isVideo,
  };

  const section = document.getElementById('admin-media-folder');
  if (!section) return;
  const unit = section.dataset.unit;
  const choose = document.getElementById('save-media-folder');
  const input = document.getElementById('admin-media-folder-input');
  const remove = document.getElementById('remove-media-folder');
  const useFolder = document.getElementById('use-folder-media');
  const useYouTube = document.getElementById('use-youtube-media');
  const sources = document.getElementById('admin-media-source');
  const youtubeForm = document.getElementById('admin-media-youtube');
  const status = document.getElementById('admin-media-folder-status');
  let useFileInput = !window.showDirectoryPicker;
  let settings = { source: 'youtube' };

  function showSource(source) {
    sources.querySelector('input[value="' + source + '"]').checked = true;
    youtubeForm.hidden = source !== 'youtube';
    section.hidden = source !== 'folder';
  }

  function show(next) {
    settings = next;
    const { folder, source } = settings;
    showSource(source);
    remove.hidden = !folder;
    useFolder.hidden = !folder || source === 'folder';
    useYouTube.hidden = source === 'youtube';
    status.textContent = folder
      ? (source === 'folder' ? 'Pasta em uso neste navegador: ' : 'YouTube em uso. Pasta salva: ') + folder.name
      : '';
    if (folder?.videos) status.textContent += '. Se os vídeos mudarem, selecione a pasta novamente.';
  }

  choose.disabled = true;
  getSettings(unit).then(show).catch(() => {
    status.textContent = 'Não foi possível consultar a pasta configurada.';
  }).finally(() => {
    choose.disabled = false;
    sources.hidden = false;
  });
  sources.addEventListener('change', event => showSource(event.target.value));

  async function update(operation) {
    const buttons = [choose, remove, useFolder, useYouTube];
    buttons.forEach(button => { button.disabled = true; });
    try {
      show(await operation());
    } catch (error) {
      if (error.name !== 'AbortError') {
        status.textContent = error.name === 'QuotaExceededError'
          ? 'Espaço insuficiente no navegador. Escolha a pasta diretamente no painel.'
          : 'Não foi possível atualizar a pasta neste navegador. Você pode escolhê-la diretamente no painel.';
      }
    } finally {
      buttons.forEach(button => { button.disabled = false; });
    }
  }

  function save(source, folder) {
    return update(async () => {
      const next = { source, folder };
      await access('readwrite', store => store.put(next, unit));
      return next;
    });
  }

  choose.addEventListener('click', async () => {
    if (useFileInput) {
      input.click();
      return;
    }
    try {
      await save('folder', await window.showDirectoryPicker({ mode: 'read' }));
    } catch (error) {
      if (error.name !== 'AbortError') {
        useFileInput = true;
        status.textContent = 'Clique em Escolher pasta novamente para usar o seletor alternativo.';
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
    save('folder', { name: videos[0].path.split('/')[0], videos });
  });
  useYouTube.addEventListener('click', () => save('youtube', settings.folder));
  useFolder.addEventListener('click', () => save('folder', settings.folder));
  remove.addEventListener('click', () => update(async () => {
    await access('readwrite', store => store.delete(unit));
    return { source: 'youtube' };
  }));
})();
