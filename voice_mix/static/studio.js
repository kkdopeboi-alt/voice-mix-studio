/* Layout shell. Existing editing controls and rendering entry points stay shared. */
(() => {
  const wrap = document.querySelector('.wrap');
  const steps = [...wrap.querySelectorAll(':scope > .step')];
  const [projects, script, voice, options, assets, progress] = steps;
  const exportButton = document.getElementById('btn-go');
  const draftButton = [...wrap.querySelectorAll(':scope > button')].find(b => b.textContent.includes('粗剪'));
  const cancelButton = [...wrap.querySelectorAll(':scope > button')].find(b => b.textContent.includes('取消'));
  const offline = document.getElementById('offline-tip');
  const shell = document.createElement('div');
  shell.className = 'studio';
  shell.innerHTML = `
    <header class="studio-header">
      <div class="brand"><svg viewBox="0 0 32 32" aria-hidden="true"><path d="M5 8h7l4 8 4-8h7L16 28z" fill="currentColor"/><path d="M5 4h22v3H5z" fill="currentColor" opacity=".4"/></svg><div>VoiceMix <span>STUDIO</span></div></div>
      <div class="document-label"><span class="status-dot"></span><span id="studio-project-label">未命名项目</span></div>
      <div class="header-actions"><button id="project-toggle" class="quiet-button">项目管理</button><span class="header-divider"></span><div id="studio-actions"></div></div>
    </header>
    <div id="studio-alert"></div>
    <div class="studio-workspace">
      <aside class="source-panel"><div class="panel-caption"><span>创作素材</span><span class="eyebrow">SOURCE</span></div><div id="source-content"></div></aside>
      <main class="canvas-panel">
        <div class="canvas-toolbar"><div class="preview-tabs" role="tablist" aria-label="预览内容"><button data-preview="subtitle" role="tab" aria-selected="true">画面预览</button><button data-preview="cover" role="tab" aria-selected="false">封面</button><button data-preview="video" role="tab" aria-selected="false">成片</button></div><span class="format-pill">9:16 · 1080p</span></div>
        <div class="stage" id="studio-stage"><div class="stage-grid"></div><div id="design-stage"></div><video id="studio-player" controls hidden></video><div id="video-empty" hidden><span class="empty-icon">▷</span><strong>让文案成为画面</strong><p>生成粗剪后，在这里播放并检查节奏。</p></div></div>
        <div class="canvas-footer"><span><span class="live-dot"></span>样式实时预览</span><span>文字 · 画面 · 声音</span></div>
        <div id="stage-controls"></div>
        <div class="workspace-note">从左侧开始写作，在右侧完成风格设置。</div>
      </main>
      <aside class="inspector"><div class="panel-caption"><span>制作面板</span><span class="eyebrow">INSPECTOR</span></div><nav class="inspector-tabs" aria-label="制作设置"></nav><div id="inspector-content"></div></aside>
    </div>
    <section class="output-dock"><div class="dock-heading"><div><span class="eyebrow">TIMELINE & OUTPUT</span><h2>剪辑与成片</h2></div><div id="dock-actions"></div></div><div id="output-empty"><span class="timeline-mark">＋</span><div><strong>你的第一条作品，从一段文案开始</strong><p>生成粗剪后，可以调整镜头、字幕和封面，再导出正式版本。</p></div></div><div id="dock-content"></div></section>
    <footer class="studio-status"><span id="engine-status">正在连接剪辑引擎</span><span id="desktop-status">VoiceMix Studio</span></footer>
    <dialog id="project-dialog"><div class="dialog-heading"><h2>项目管理</h2><button id="close-project" aria-label="关闭项目管理">×</button></div><div id="project-content"></div></dialog>`;
  document.body.prepend(shell);
  const byId = id => document.getElementById(id);
  byId('studio-actions').append(draftButton, exportButton);
  draftButton.textContent = '生成样板预览'; draftButton.hidden=true;
  exportButton.textContent = '生成样板预览';
  const invalidatePreviews = event => {
    if (!event.target.closest('#inspector-content')) return;
    if (event.target.closest('#cover-chips') || ['include-cover','cover-title'].includes(event.target.id)) return;
    document.querySelectorAll('.cut-editor').forEach(editor=>{
      const button=editor.querySelector('[data-confirm-export]');
      if(button){editor.dataset.dirty='true';button.disabled=true;}
    });
  };
  document.addEventListener('input',invalidatePreviews);
  document.addEventListener('change',invalidatePreviews);
  byId('dock-actions').append(cancelButton);
  byId('studio-alert').append(offline);
  byId('source-content').append(script, assets);
  script.classList.add('script-card');
  assets.classList.add('asset-card');
  byId('project-content').append(projects);
  byId('dock-content').append(progress);
  const result = byId('result-grid');
  byId('dock-content').append(result);
  byId('project-toggle').onclick = () => byId('project-dialog').showModal();
  byId('close-project').onclick = () => byId('project-dialog').close();
  byId('project-name').addEventListener('input', () => { byId('studio-project-label').textContent = byId('project-name').value || '未命名项目'; });

  const panels = {};
  const categories = [['layout', '画面'], ['voice', '声音'], ['rhythm', '节奏'], ['filter', '调色'], ['subtitle', '字幕'], ['cover', '封面']];
  for (const [id, title] of categories) {
    const panel = document.createElement('section');
    panel.className = 'inspector-page'; panel.id = 'inspector-' + id; panel.hidden = id !== 'layout';
    const button = document.createElement('button');
    button.textContent = title; button.className = id === 'layout' ? 'selected' : '';
    button.setAttribute('aria-pressed', String(id === 'layout'));
    button.onclick = () => {
      for (const page of Object.values(panels)) page.hidden = page !== panel;
      shell.querySelectorAll('.inspector-tabs button').forEach(b => { b.classList.toggle('selected', b === button); b.setAttribute('aria-pressed', String(b === button)); });
    };
    shell.querySelector('.inspector-tabs').append(button);
    byId('inspector-content').append(panel); panels[id] = panel;
  }
  panels.voice.append(voice);
  let target = panels.layout;
  for (const node of [...options.children]) {
    if (node.classList.contains('step-head') || node.classList.contains('divider')) continue;
    if (node.classList.contains('sec-label')) {
      const label = node.textContent;
      if (label.includes('自然表达')) target = panels.rhythm;
      if (label.includes('全局视频滤镜')) target = panels.filter;
      if (label.includes('字幕样式')) target = panels.subtitle;
      if (label.includes('封面设计')) target = panels.cover;
      if (label.includes('背景音乐')) target = panels.voice;
    }
    if (node.classList.contains('design-previews')) {
      byId('design-stage').append(node);
    } else if (node.querySelector('#design-image')) {
      byId('stage-controls').append(node);
    } else target.append(node);
  }
  // Transition controls belong to rhythm, alongside speech pauses.
  const transitions = byId('trans-style').closest('.row');
  panels.rhythm.prepend(transitions);
  wrap.remove();
  document.querySelector('#script').placeholder = '写下你想讲的故事…\n\n一句文案，一个画面。让声音带着观众，慢慢进入你的表达。';
  document.querySelector('#cover-title').placeholder = '为这条作品写一个标题';
  document.querySelector('#src-dir').placeholder = '选择素材目录或单个文件';
  const nativeButton = (text, kind, targetId) => {
    const button = document.createElement('button');
    button.className = 'native-picker'; button.textContent = text;
    button.onclick = async () => {
      if (!window.pywebview?.api) return toast('浏览器模式可直接输入路径；桌面版支持系统文件选择器。');
      try {
        const path = await window.pywebview.api.choose_path(kind);
        if (path) { byId(targetId).value = path; if (targetId === 'src-dir') await doScan(); }
      } catch (error) { toast(error.message || '文件选择失败', true); }
    };
    return button;
  };
  const pickers = document.createElement('div'); pickers.className = 'native-picker-row';
  pickers.append(nativeButton('导入文件夹', 'source-folder', 'src-dir'), nativeButton('导入文件', 'source-file', 'src-dir'));
  byId('src-dir').closest('.row').before(pickers);
  byId('out-dir').after(nativeButton('选择输出位置', 'output', 'out-dir'));
  const setPreview = mode => {
    const figures = [...byId('design-stage').querySelectorAll('figure')];
    figures.forEach((figure, i) => figure.hidden = mode === 'video' || i !== (mode === 'cover' ? 1 : 0));
    byId('studio-player').hidden = mode !== 'video' || !byId('studio-player').getAttribute('src');
    byId('video-empty').hidden = mode !== 'video' || !!byId('studio-player').getAttribute('src');
    if (mode !== 'video') byId('studio-player').pause();
    shell.querySelectorAll('[data-preview]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.preview === mode)));
  };
  shell.querySelectorAll('[data-preview]').forEach(b => { b.onclick = () => setPreview(b.dataset.preview); });
  setPreview('subtitle');
  new MutationObserver(() => {
    const cards = byId('videos').querySelectorAll('.vcard');
    byId('output-empty').hidden = cards.length > 0;
    cards.forEach(card => {
      if (card.dataset.studioBound) return;
      card.dataset.studioBound = '1';
      const button = document.createElement('button'); button.className = 'watch-button'; button.textContent = '在画布播放';
      button.onclick = () => { byId('studio-player').src = card.querySelector('.vshow').dataset.video; setPreview('video'); };
      card.querySelector('.vc-info').append(button);
    });
  }).observe(byId('videos'), {childList:true, subtree:true});
  window.addEventListener('pywebviewready', () => { byId('desktop-status').textContent = '桌面工作台 · 本地处理'; });
  // The API carries platform paths and engine status, so nothing assumes a D: drive.
  studioMetadata().then(meta => {
    byId('engine-status').textContent = meta.engine_ready ? '● 剪辑引擎就绪' : '需要配置 FFmpeg';
    byId('desktop-status').textContent = 'VoiceMix Studio v' + (meta.version || '') + ' · 文案批量 / MV';
    if (!meta.engine_ready) {
      const configure = document.createElement('button'); configure.textContent = '选择 FFmpeg 目录';
      configure.onclick = async () => {
        if (!window.pywebview?.api) return toast('请安装 FFmpeg 和 ffprobe，并加入 PATH 后重新启动。');
        try { if (await window.pywebview.api.configure_ffmpeg()) toast('已保存工具目录，请关闭并重新打开应用。'); }
        catch (error) { toast(error.message || '配置失败', true); }
      };
      byId('studio-alert').append(configure);
    }
  }).catch(() => { byId('engine-status').textContent = '剪辑引擎未连接'; });
})();
