(() => {
  const media = document.getElementById('panel-media');
  const input = document.getElementById('media-folder');
  const choose = document.getElementById('choose-media-folder');
  const allow = document.getElementById('allow-media-folder');
  const restore = document.getElementById('restore-panel-media');
  const status = document.getElementById('media-folder-status');
  const defaultMedia = media.firstElementChild.cloneNode(true);
  const order = new Intl.Collator('pt-BR', { numeric: true });
  const video = document.createElement('video');
  video.controls = true;
  video.muted = true;
  video.playsInline = true;

  let files = [];
  let index = 0;
  let failures = 0;
  let source = null;
  let configuredFolder;
  let selection = 0;

  function releaseVideo() {
    if (!source) return;
    video.removeAttribute('src');
    video.load();
    URL.revokeObjectURL(source);
    source = null;
  }

  function playNext() {
    releaseVideo();
    const nextSource = URL.createObjectURL(files[index].file);
    source = nextSource;
    video.src = source;
    index = (index + 1) % files.length;
    video.play().catch(error => {
      if (source === nextSource && error.name === 'NotAllowedError') {
        status.textContent = 'Pressione Reproduzir para iniciar os vídeos.';
      }
    });
  }

  function restoreDefault(message = '') {
    releaseVideo();
    files = [];
    const replacement = defaultMedia.cloneNode(true);
    media.replaceChildren(replacement);
    window.painelMedia.select(media.querySelector('video'), media.querySelector('iframe'));
    restore.hidden = true;
    status.textContent = message;
  }

  choose.addEventListener('click', () => input.click());
  restore.addEventListener('click', () => {
    selection += 1;
    restoreDefault();
  });
  input.addEventListener('change', () => {
    const selected = Array.from(input.files);
    input.value = '';
    selection += 1;
    playFiles(selected.map(file => ({ file, path: file.webkitRelativePath })));
  });

  function playFiles(selected) {
    const videos = selected.filter(({ file }) =>
      file.type.startsWith('video/') || /\.(mp4|m4v|webm|ogv|mov|mkv|avi|mpeg|mpg)$/i.test(file.name)
    );
    if (!videos.length) {
      status.textContent = 'Nenhum vídeo encontrado na pasta.';
      return;
    }
    files = videos.sort((a, b) => order.compare(a.path, b.path));
    allow.hidden = true;
    index = 0;
    failures = 0;
    status.textContent = '';
    if (video.parentNode !== media) {
      window.painelMedia.select(video);
      media.replaceChildren(video);
    }
    restore.hidden = false;
    playNext();
  }

  async function readFolder(folder, result, prefix = '') {
    for await (const entry of folder.values()) {
      const path = prefix + entry.name;
      if (entry.kind === 'directory') await readFolder(entry, result, path + '/');
      else result.push({ file: await entry.getFile(), path });
    }
  }

  async function playConfigured(requestPermission) {
    const current = ++selection;
    try {
      const permission = requestPermission
        ? await configuredFolder.requestPermission({ mode: 'read' })
        : await configuredFolder.queryPermission({ mode: 'read' });
      if (current !== selection) return;
      allow.hidden = permission === 'granted';
      if (!allow.hidden) return;
      const selected = [];
      await readFolder(configuredFolder, selected);
      if (current === selection) playFiles(selected);
    } catch {
      if (current === selection) status.textContent = 'Não foi possível acessar a pasta configurada. Escolha uma pasta de vídeos.';
    }
  }

  allow.addEventListener('click', () => playConfigured(true));
  if (media.dataset.unit && window.showDirectoryPicker) {
    window.painelFolderSettings.get(media.dataset.unit).then(folder => {
      configuredFolder = folder;
      if (folder && selection === 0) return playConfigured(false);
    }).catch(() => {
      if (selection === 0) status.textContent = 'Não foi possível consultar a pasta configurada.';
    });
  }

  video.addEventListener('ended', () => {
    if (source) playNext();
  });
  video.addEventListener('playing', () => {
    failures = 0;
    status.textContent = '';
  });
  video.addEventListener('error', () => {
    if (!source) return;
    failures += 1;
    if (failures >= files.length) restoreDefault('O navegador não conseguiu reproduzir os vídeos da pasta.');
    else playNext();
  });
})();
