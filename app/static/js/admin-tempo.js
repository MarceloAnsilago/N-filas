(() => {
  const form = document.getElementById('admin-weather');
  const uf = form.elements.uf;
  const city = form.elements.municipio;
  const save = form.querySelector('button[type="submit"]');
  const status = document.getElementById('weather-settings-status');
  const order = new Intl.Collator('pt-BR');
  const selected = { [uf.value]: city.value };
  let previousUf = uf.value;
  let catalog;

  uf.addEventListener('change', async () => {
    const state = uf.value;
    city.disabled = save.disabled = true;
    status.textContent = 'Carregando municípios…';
    try {
      catalog ??= fetch(form.dataset.catalog).then(response => {
        if (!response.ok) throw new Error('Catálogo indisponível');
        return response.json();
      });
      const states = await catalog;
      if (uf.value !== state) return;
      const cities = Object.entries(states[state].municipios)
        .sort(([, a], [, b]) => order.compare(a.nome, b.nome));
      city.replaceChildren(new Option('Selecione o município', ''));
      for (const [id, item] of cities) city.add(new Option(item.nome, id));
      city.value = selected[state] || '';
      previousUf = state;
      status.textContent = '';
    } catch {
      catalog = undefined;
      if (uf.value !== state) return;
      uf.value = previousUf;
      status.textContent = 'Não foi possível carregar os municípios. Tente novamente.';
    }
    city.disabled = save.disabled = false;
  });

  city.addEventListener('change', () => {
    selected[uf.value] = city.value;
  });
})();
