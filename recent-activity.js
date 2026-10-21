(() => {
  const section = document.querySelector('#recent-activity');
  if (!section) return;

  const copy = {
    en: { title: 'Recent public activity', lead: 'Latest entries from Letterboxd.', snapshot: 'The analysis below was last rebuilt on', unavailable: 'Recent activity is temporarily unavailable.' },
    zh: { title: '近期公开动态', lead: '来自 Letterboxd 的最新记录。', snapshot: '下方分析上次完整生成于', unavailable: '近期动态暂时无法加载。' },
  };
  let feed;

  function render() {
    const language = document.documentElement.lang.startsWith('zh') ? 'zh' : 'en';
    const t = copy[language];
    section.querySelector('h2').textContent = t.title;
    section.querySelector('.recent-lead').textContent = t.lead;
    section.querySelector('.snapshot-note').textContent = `${t.snapshot} ${section.dataset.snapshotDate}.`;
    const list = section.querySelector('ol');
    list.replaceChildren();
    if (!feed) {
      const note = document.createElement('li');
      note.textContent = t.unavailable;
      list.append(note);
      return;
    }
    const seen = new Set();
    const recentFilms = feed.items.filter(item => {
      const key = `${item.title}:${item.year}`;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    }).slice(0, 8);
    for (const item of recentFilms) {
      const row = document.createElement('li');
      const link = document.createElement('a');
      link.href = item.url;
      link.textContent = `${item.title} (${item.year})${item.rating ? ` · ★ ${item.rating}` : ''}`;
      const date = document.createElement('time');
      date.dateTime = item.published_at;
      const locale = language === 'zh' ? 'zh-CN' : 'en-CA';
      const format = value => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(new Date(value));
      const added = format(item.published_at);
      const watched = item.watched_date ? format(`${item.watched_date}T12:00:00Z`) : '';
      date.textContent = language === 'zh'
        ? `发布 ${added}${watched ? ` · 观看 ${watched}` : ''}`
        : `Added ${added}${watched ? ` · Watched ${watched}` : ''}`;
      row.append(link, date);
      list.append(row);
    }
  }

  fetch('recent-activity.json', { cache: 'no-cache' })
    .then(response => { if (!response.ok) throw new Error('Recent activity unavailable'); return response.json(); })
    .then(data => { feed = data; render(); })
    .catch(render);
  document.querySelectorAll('[data-language-choice]').forEach(button => {
    button.addEventListener('click', () => queueMicrotask(render));
  });
})();
