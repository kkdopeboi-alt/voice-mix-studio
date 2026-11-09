/* Music-first editor, independent of the narration workflow. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const shell = document.querySelector('.studio');
  if (!shell) return;
  const mode = document.createElement('nav'); mode.className='mode-tabs';mode.setAttribute('aria-label','创作模式');
  mode.innerHTML='<button aria-selected="true">文案混剪</button><button aria-selected="false">音乐 MV</button>';
  shell.querySelector('.brand').after(mode);
  const root=document.createElement('section');root.className='mv-app';root.hidden=true;
  root.innerHTML=`
  <div class="mv-top"><h1>音乐 MV</h1><span class="mv-status" id="mv-status" role="status" aria-live="polite">让画面跟随歌声，让故事留在音乐里。</span><button id="mv-cancel" hidden>取消任务</button><button id="mv-save">保存项目</button><button class="btn-primary" id="mv-preview">生成低清粗剪</button><button id="mv-export">预览通过，确认导出</button></div>
  <div class="mv-busy" hidden id="mv-progress"><span></span></div>
  <div class="mv-grid">
    <aside class="mv-panel"><h2>01 / 歌曲与素材</h2><div class="mv-body">
      <div class="mv-row"><select id="mv-projects" aria-label="恢复 MV 项目"><option value="">恢复 MV 项目…</option></select><button id="mv-new">新建</button></div>
      <label for="mv-name">作品名称</label><input id="mv-name" value="我的第一支 MV">
      <label for="mv-audio-path">歌曲</label><input id="mv-audio-path" placeholder="歌曲完整路径或上传音频">
      <div class="mv-actions"><button id="mv-pick-audio">本地选择</button><button id="mv-upload-audio">上传歌曲</button></div><input hidden type="file" id="mv-audio-file" accept="audio/*">
      <label for="mv-input">歌词来源</label><select id="mv-input"><option value="text">纯文字歌词 · 自动对齐</option><option value="auto">只有歌曲 · 自动识别</option><option value="lrc">带时间的 LRC 歌词</option></select>
      <textarea id="mv-lyrics" rows="6" placeholder="每行一句歌词，重复演唱的段落也请完整填写。"></textarea>
      <div class="mv-actions"><button id="mv-import-lyrics">导入 TXT / LRC</button><button id="mv-analyze">分析歌词时间</button></div><input hidden type="file" id="mv-lyrics-file" accept=".lrc,.txt">
      <small>识别与对齐在本机完成。首次使用下载语音模型；歌曲混响可能导致误识别，黄色标记需要检查。普通 LRC 的逐字时间为估算，可手动校正。</small>
      <label for="mv-model">识别模型</label><select id="mv-model"><option value="base">标准 · base（约 145 MB）</option><option value="small">精细 · small（约 480 MB）</option><option value="tiny">轻量 · tiny（约 75 MB）</option></select>
      <hr><label for="mv-paths">素材文件或文件夹 · 每行一个路径</label><textarea id="mv-paths" rows="3" placeholder="选择本地素材，或上传视频和图片"></textarea>
      <div class="mv-actions"><button id="mv-pick-assets">选择文件夹</button><button id="mv-upload-assets">上传素材</button><button id="mv-add-assets">加入项目</button></div><input hidden type="file" id="mv-assets-file" accept="video/*,image/*" multiple>
      <label for="mv-url">URL 直接作为 MV 背景</label><div class="mv-row"><input id="mv-url" type="url" placeholder="https://…"><button id="mv-download">导入背景</button></div>
      <small>自动缓存并直接进入背景预览，无需再上传；正式导出使用完整下载质量。</small>
      <label>站点登录验证（可选）</label><select id="mv-auth"><option value="">不使用登录态</option><option value="edge">读取 Edge 登录态</option><option value="chrome">读取 Chrome 登录态</option><option value="firefox">读取 Firefox 登录态</option><option value="safari">读取 Safari 登录态（Mac）</option><option value="cookies">导入 cookies.txt</option></select>
      <input id="mv-cookies" type="file" accept=".txt" hidden><small>仅在你主动选择后读取登录态。Cookie 文件只用于本次导入，完成后删除，不写入项目或导出文件。</small>
      <div id="mv-background-controls" hidden><label class="mv-check"><input id="mv-use-background" type="checkbox" checked>使用此 URL 视频作为连续背景</label><div class="mv-row"><label>入点（秒）<input id="mv-bg-start" type="number" min="0" step=".1" value="0"></label><label>出点（秒）<input id="mv-bg-end" type="number" min=".1" step=".1" value="1"></label></div><label>水平构图中心<input id="mv-bg-x" type="range" min="0" max="1" step=".01" value=".5"></label><label>垂直构图中心<input id="mv-bg-y" type="range" min="0" max="1" step=".01" value=".5"></label><button id="mv-bg-play">预览选中区间</button><small>编排镜头时应用；片段短于歌曲时按“允许重复”选项处理。之后仍可在镜头时间轴微调。</small></div>
      <label class="mv-check"><input type="checkbox" id="mv-visual" checked>分析画面内容，辅助匹配歌词意境</label><small>首次下载约 155 MB 场景模型。关闭后按文件名和自填标签匹配。</small>
      <label class="mv-check"><input type="checkbox" id="mv-reuse" checked>允许重复使用素材</label>
      <div class="mv-asset-list" id="mv-asset-list"></div>
    </div></aside>
    <main><section class="mv-panel"><h2>02 / 试听与画面</h2>
      <div class="mv-stage" id="mv-stage"><div class="mv-placeholder"><strong>一首歌，一段故事。</strong>导入音乐与素材，开始制作你的 MV。</div><video id="mv-video" controls hidden></video><img id="mv-image" hidden alt="当前镜头构图"><div class="mv-lyric-overlay" id="mv-overlay" hidden></div></div>
      <div class="mv-body"><canvas class="mv-wave" id="mv-wave" width="1000" height="65" aria-label="歌曲波形，点击定位"></canvas><input type="range" id="mv-seek" min="0" max="1" step=".01" value="0" aria-label="歌曲时间轴"><div class="mv-clock" id="mv-clock">00:00 / 00:00</div><audio id="mv-audio" class="mv-audio" controls></audio>
      <small id="mv-preview-note">编辑时歌词叠层用于校时；生成的粗剪展示实际导出效果。</small>
      <label for="mv-range-mode">制作范围</label><select id="mv-range-mode"><option value="full">整首歌曲</option><option value="highlight">精彩片段 · 推荐后可调整</option></select>
      <div class="mv-row"><label>起点（秒）<input id="mv-range-start" type="number" min="0" step=".01" value="0"></label><label>终点（秒）<input id="mv-range-end" type="number" min="1" step=".01" value="1"></label><button id="mv-apply-range">应用范围</button></div><div id="mv-recs" class="mv-recs"></div>
      <div class="mv-actions"><button id="mv-plan">编排镜头</button><button id="mv-regen">只重做未锁定镜头</button><button id="mv-edit-view">返回歌词校时预览</button></div>
      </div></section><section class="mv-panel mv-timeline"><h2>镜头时间轴 <small>金色底边表示意境替代；点击镜头调整，锁定后局部重做会保留该镜头。</small></h2><div class="mv-strip" id="mv-strip"></div></section>
    </main>
    <aside class="mv-panel mv-inspector"><h2>03 / 风格与精修</h2><div class="mv-body"><section>
      <label for="mv-style">MV 风格</label><select id="mv-style"><option value="cinema">电影叙事 · 克制切镜</option><option value="mood">情绪写真 · 舒缓停留</option><option value="beat">节奏混剪 · 重拍候选切镜</option><option value="stage">舞台演唱 · 演唱镜头优先</option></select>
      <label for="mv-aspect">画幅</label><select id="mv-aspect"><option>9:16</option><option>16:9</option><option>1:1</option></select>
      <label for="mv-lyric-style">歌词显示</label><select id="mv-lyric-style"><option value="line">逐句字幕</option><option value="karaoke">逐字变色</option><option value="scroll">上下滚动</option></select>
      <label for="mv-font">字体</label><select id="mv-font"></select>
      <label for="mv-size">字号 <output id="mv-size-label">3.5%</output></label><input id="mv-size" type="range" min=".015" max=".1" step=".001" value=".035">
      <div class="mv-row"><label>文字<input id="mv-color" type="color" value="#ffffff"></label><label>高亮<input id="mv-highlight" type="color" value="#c4ef8b"></label></div>
      <label for="mv-y">歌词位置</label><input id="mv-y" type="range" min=".15" max=".9" step=".01" value=".78">
      <label for="mv-mask">歌词蒙版</label><input id="mv-mask" type="range" min="0" max="1" step=".05" value=".2">
      <label for="mv-filter">全局画面滤镜</label><select id="mv-filter"><option value="none">原色</option><option value="warm" selected>暖调</option><option value="cool">冷调</option><option value="soft">柔和</option><option value="clear">清透</option><option value="mono">黑白</option></select>
      <small>画面滤镜不会覆盖歌词。舞台演唱风格优先使用已有演唱素材，不生成歌手表演。</small>
      <label for="mv-resolution">正式导出分辨率</label><select id="mv-resolution"><option value="1080p">1080p 高清</option><option value="4k">4K 超清（需要高清原素材）</option></select><label for="mv-bitrate">正式导出码率</label><select id="mv-bitrate"><option value="20">20 Mbps · 约 150 MB/分钟</option><option value="40" selected>40 Mbps · 约 300 MB/分钟</option><option value="80">80 Mbps · 约 600 MB/分钟</option></select><small>低清粗剪仅供校时，分享请使用“导出高清成片”。增大码率无法恢复低清原素材的细节。</small><label for="mv-out">输出目录</label><input id="mv-out" placeholder="留空使用默认视频目录">
      </section><section><hr><div id="mv-shot-editor"><small>点击时间轴或某句歌词，定位对应镜头。</small></div><hr><label>导出版本</label><div id="mv-history" class="mv-history"></div></section></div></aside>
  </div>
  <section class="mv-panel mv-timeline"><h2>歌词时间轴 <small>点击“定位”试听；可修改歌词、句子时间及逐字时间。修改后保存项目，再生成粗剪检查。</small></h2><div class="mv-table-wrap"><table class="mv-table"><thead><tr><th>试听</th><th>歌词 / 逐字时间</th><th>起点（秒）</th><th>终点（秒）</th><th>校对</th></tr></thead><tbody id="mv-lyric-rows"></tbody></table></div></section>`;
  shell.append(root);
  let importedBackground=null,backgroundApplied='';
  let project=null, selected=0, taskId=null, rendered=false, uploading=0;
  const original=[...shell.children].filter(x=>x!==root&&!x.classList.contains('studio-header')&&!x.classList.contains('studio-status'));
  // The existing header has no class in older builds; preserve it explicitly.
  const header=mode.closest('header');
  mode.querySelectorAll('button').forEach((button,index)=>button.onclick=()=>{
    const mv=index===1;root.hidden=!mv;
    original.forEach(el=>{if(el!==header)el.hidden=mv;});
    header.querySelector('.header-actions').hidden=mv;
    mode.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-selected',String(i===index)));
    if(mv) refreshProjects(); else {$('mv-audio').pause();$('mv-video').pause();}
  });
  const status=(message,error=false)=>{$('mv-status').textContent=message;$('mv-status').classList.toggle('danger',error);};
  async function api(path,body,method='POST'){
    const response=await fetch('/api/mv'+path,body===undefined?{}:{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data;
  }
  function action(fn){return async()=>{try{await fn();}catch(e){status(e.message,true);}};}
  function busy(value){root.querySelectorAll('button').forEach(b=>{if(b.id!=='mv-cancel')b.disabled=value;});$('mv-cancel').hidden=!value;$('mv-progress').hidden=!value;}
  async function job(path,body){
    busy(true);
    try{
      const started=await api(path,body);taskId=started.task_id;
      while(true){
        const result=await api('/tasks/'+taskId);status(result.detail||result.status);$('mv-progress').firstElementChild.style.width=result.pct+'%';
        if(result.status==='done')return result.result;
        if(['error','cancelled'].includes(result.status)){
          if(result.error_code==='materials_exhausted'&&confirm('无可用新素材，是否允许使用老素材？取消后可继续补充素材。')){$('mv-reuse').checked=true;if(project){project.settings.allow_reuse=true;await saveProject();}status('已允许复用，请重新编排镜头。');}
          throw new Error(result.error||'任务已取消');
        }
        await new Promise(resolve=>setTimeout(resolve,850));
      }
    }finally{taskId=null;busy(false);}
  }
  $('mv-cancel').onclick=action(async()=>{if(taskId){await api('/tasks/'+taskId+'/cancel',{});status('正在取消，会在当前处理步骤结束后停止。');}});
  async function uploadFile(file){
    uploading++;busy(true);status('正在导入 '+file.name);
    try{const r=await fetch('/api/mv/upload?name='+encodeURIComponent(file.name),{method:'POST',body:file});const j=await r.json();if(!r.ok)throw new Error(j.detail);return j.path;}
    finally{uploading--;if(!uploading)busy(false);}
  }
  async function choose(kind){if(!window.pywebview?.api)throw new Error('浏览器模式请上传文件或输入完整路径；桌面版可打开本地选择器。');return window.pywebview.api.choose_path(kind);}
  const addPaths=paths=>{$('mv-paths').value=[...new Set([...$('mv-paths').value.split('\n').filter(Boolean),...paths])].join('\n');};
  $('mv-pick-audio').onclick=action(async()=>{const path=await choose('source-file');if(path)$('mv-audio-path').value=path;});
  $('mv-pick-assets').onclick=action(async()=>{const path=await choose('source-folder');if(path)addPaths([path]);});
  $('mv-upload-audio').onclick=()=>$('mv-audio-file').click();
  $('mv-audio-file').onchange=action(async()=>{if($('mv-audio-file').files[0])$('mv-audio-path').value=await uploadFile($('mv-audio-file').files[0]);status('歌曲已导入');});
  $('mv-upload-assets').onclick=()=>$('mv-assets-file').click();
  $('mv-assets-file').onchange=action(async()=>{for(const f of $('mv-assets-file').files)addPaths([await uploadFile(f)]);status('素材已导入，生成粗剪时自动加入。');});
  $('mv-import-lyrics').onclick=()=>$('mv-lyrics-file').click();
  $('mv-lyrics-file').onchange=action(async()=>{const f=$('mv-lyrics-file').files[0];if(f){$('mv-lyrics').value=await f.text();$('mv-input').value=f.name.toLowerCase().endsWith('.lrc')?'lrc':'text';$('mv-input').dispatchEvent(new Event('change'));}});
  $('mv-input').onchange=()=>{$('mv-lyrics').hidden=$('mv-input').value==='auto';};
  $('mv-auth').onchange=()=>{$('mv-cookies').hidden=$('mv-auth').value!=='cookies';};
  $('mv-download').onclick=action(async()=>{
    let cookie_id='';const auth=$('mv-auth').value;
    if(auth==='cookies') {
      const file=$('mv-cookies').files[0];if(!file)throw new Error('请先选择 cookies.txt');
      const response=await fetch('/api/mv/cookies',{method:'POST',body:file});const data=await response.json();
      if(!response.ok)throw new Error(data.detail);cookie_id=data.cookie_id;
    }
    rendered=false;
    const result=await job('/download',{url:$('mv-url').value.trim(),browser:auth==='cookies'?'':auth,cookie_id});
    addPaths(result.paths);
    if(project)await addAssets();
    if(result.video_name){
      importedBackground={path:result.paths.find(p=>p.endsWith(result.video_name))};
      $('mv-background-controls').hidden=false;$('mv-bg-start').value=0;$('mv-bg-end').value=result.duration;
      const v=$('mv-video');$('mv-audio').pause();$('mv-image').hidden=true;$('mv-overlay').hidden=true;
      $('mv-stage').querySelector('.mv-placeholder').hidden=true;
      v.src='/api/mv/imports/'+result.import_id+'/media?name='+encodeURIComponent(result.video_name);
      v.hidden=false;v.controls=true;v.muted=false;v.style.objectFit='cover';
      $('mv-preview-note').textContent='URL 背景已导入，可直接预览、裁剪区间和调整构图。编排后可继续修改镜头。';
    }
    status('URL 已直接导入背景，无需下载后再次上传。');
  });
  const background=()=>importedBackground&&$('mv-use-background').checked?{...importedBackground,start:+$('mv-bg-start').value,end:+$('mv-bg-end').value,focal_x:+$('mv-bg-x').value,focal_y:+$('mv-bg-y').value}:null;
  $('mv-bg-play').onclick=action(async()=>{const v=$('mv-video');v.currentTime=+$('mv-bg-start').value;await v.play();});
  $('mv-video').addEventListener('timeupdate',()=>{if(!$('mv-background-controls').hidden&&!rendered&&$('mv-video').currentTime>=+$('mv-bg-end').value)$('mv-video').pause();});
  for(const id of ['mv-bg-x','mv-bg-y'])$(id).oninput=()=>{$('mv-video').style.objectPosition=(+$('mv-bg-x').value*100)+'% '+(+$('mv-bg-y').value*100)+'%';};
  const settings=()=>({resolution:$('mv-resolution').value,bitrate_mbps:+$('mv-bitrate').value,style:$('mv-style').value,aspect:$('mv-aspect').value,lyric_style:$('mv-lyric-style').value,
    font:$('mv-font').value,font_size:+$('mv-size').value,color:$('mv-color').value,highlight:$('mv-highlight').value,
    lyric_y:+$('mv-y').value,mask:+$('mv-mask').value,filter:$('mv-filter').value,allow_reuse:$('mv-reuse').checked});
  async function createProject(){
    if(uploading)throw new Error('请等待上传完成');
    project=await api('/projects',{name:$('mv-name').value,audio:$('mv-audio-path').value.trim(),source_paths:$('mv-paths').value.split('\n').map(x=>x.trim()).filter(Boolean),
      lyrics:$('mv-lyrics').value,lyric_input:$('mv-input').value,model:$('mv-model').value,visual_analysis:$('mv-visual').checked,settings:settings()});
    showProject();await refreshProjects();
  }
  async function saveProject(){if(!project){await createProject();return;}project.name=$('mv-name').value;project.settings=settings();project.visual_analysis=$('mv-visual').checked;project=await api('/projects/'+project.id,{version:project.version,project},'PUT');status('项目已保存');}
  async function addAssets(){if(!project){await createProject();return;}const paths=$('mv-paths').value.split('\n').map(x=>x.trim()).filter(Boolean);if(paths.length){project=await api('/projects/'+project.id+'/assets',{paths});drawAssets();}}
  async function analyze(){if(!project)await createProject();else if($('mv-audio-path').value.trim()!==project.audio||$('mv-lyrics').value!==project.lyric_text||$('mv-input').value!==project.lyric_input){await createProject();}const result=await job('/projects/'+project.id+'/analyze',{});project=result.project;backgroundApplied=JSON.stringify(background());showProject();}
  async function planning(regenerate=false){if(!project||!project.lyrics.length)await analyze();await saveProject();await addAssets();regenerate=regenerate||project.clips.some(c=>c.locked);const result=await job('/projects/'+project.id+'/plan',{regenerate,background:background()});project=result.project;backgroundApplied=JSON.stringify(background());showProject();}
  async function render(preview){if(!project||!project.lyrics.length)await analyze();if(!project.clips.length||background()&&JSON.stringify(background())!==backgroundApplied)await planning();await saveProject();const result=await job('/projects/'+project.id+'/render',{preview,out_dir:$('mv-out').value.trim()});project=result.project;drawHistory();playRender(project.renders.length-1);status(preview?'MV 粗剪已完成，可继续精修。':'高清 MV 已导出。');await refreshProjects();}
  $('mv-analyze').onclick=action(analyze);$('mv-plan').onclick=action(()=>planning());$('mv-regen').onclick=action(()=>planning(true));
  $('mv-preview').onclick=action(()=>render(true));$('mv-export').onclick=action(()=>render(false));$('mv-save').onclick=action(saveProject);$('mv-add-assets').onclick=action(addAssets);
  $('mv-new').onclick=()=>{if(project&&!confirm('当前修改是否已保存？确定将开始新项目。'))return;project=null;selected=0;rendered=false;importedBackground=null;$('mv-background-controls').hidden=true;$('mv-audio').pause();$('mv-video').pause();$('mv-name').value='新的 MV';$('mv-audio-path').value='';$('mv-lyrics').value='';$('mv-paths').value='';showProject();status('已开始新 MV。');};
  async function refreshProjects(){const list=await api('/projects');$('mv-projects').innerHTML='<option value="">恢复 MV 项目…</option>'+list.map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');if(project)$('mv-projects').value=project.id;}
  $('mv-projects').onchange=action(async()=>{if(!$('mv-projects').value)return;project=await api('/projects/'+$('mv-projects').value);selected=0;showProject();status('已恢复 MV 项目');});
  function applySettings(){if(!project)return;const s=project.settings;$('mv-resolution').value=s.resolution||'1080p';$('mv-bitrate').value=s.bitrate_mbps||40;const ids={style:'mv-style',aspect:'mv-aspect',lyric_style:'mv-lyric-style',font:'mv-font',font_size:'mv-size',color:'mv-color',highlight:'mv-highlight',lyric_y:'mv-y',mask:'mv-mask',filter:'mv-filter'};for(const [key,id]of Object.entries(ids))$(id).value=s[key];$('mv-reuse').checked=s.allow_reuse;}
  function showProject(){
    rendered=false;$('mv-video').pause();$('mv-video').hidden=true;$('mv-image').hidden=true;$('mv-overlay').hidden=true;
    $('mv-stage').querySelector('.mv-placeholder').hidden=!!project;
    if(!project){$('mv-audio').removeAttribute('src');for(const id of ['mv-strip','mv-asset-list','mv-lyric-rows','mv-recs','mv-history'])$(id).replaceChildren();return;}
    $('mv-name').value=project.name;$('mv-audio-path').value=project.audio;$('mv-lyrics').value=project.lyric_text;$('mv-input').value=project.lyric_input;$('mv-input').dispatchEvent(new Event('change'));
    $('mv-model').value=project.model;$('mv-visual').checked=project.visual_analysis;
    const source='/api/mv/projects/'+project.id+'/media';if($('mv-audio').getAttribute('src')!==source)$('mv-audio').src=source;
    $('mv-seek').max=project.duration;$('mv-range-start').value=project.range[0].toFixed(2);$('mv-range-end').value=project.range[1].toFixed(2);
    $('mv-range-mode').value=project.range[0]===0&&Math.abs(project.range[1]-project.duration)<.02?'full':'highlight';
    applySettings();drawAssets();drawLyrics();drawTimeline();drawHistory();drawRecs();drawWave();showShot();updateLyrics();
  }
  function drawAssets(){if(!project)return;$('mv-asset-list').innerHTML=project.assets.map((a,i)=>`<div class="mv-asset"><label class="mv-check"><input type="checkbox" data-asset="${i}" ${a.enabled?'checked':''}>${esc(a.name)}</label><input type="text" data-tags="${i}" aria-label="${esc(a.name)}场景标签" value="${esc(a.tags)}" placeholder="补充意境：雨夜、告别、街道…"><small>${(a.scene_ids||[]).map(i=>sceneNames[i]).filter(Boolean).join(' · ')||'尚无自动场景标签'}</small></div>`).join('');
    $('mv-asset-list').querySelectorAll('[data-asset]').forEach(e=>e.onchange=()=>project.assets[+e.dataset.asset].enabled=e.checked);
    $('mv-asset-list').querySelectorAll('[data-tags]').forEach(e=>e.oninput=()=>project.assets[+e.dataset.tags].tags=e.value);
  }
  function drawLyrics(){
    $('mv-lyric-rows').innerHTML=project.lyrics.map((r,i)=>`<tr data-line="${i}"><td><button data-seek="${i}">定位 ${i+1}</button></td><td><input class="lyric-text" data-text="${i}" aria-label="第${i+1}句歌词" value="${esc(r.text)}"><details><summary>逐字校时</summary><div class="mv-words">${(r.words||[]).map((w,j)=>`<div class="mv-word"><input value="${esc(w.text)}" aria-label="歌词字词" data-word="${i}:${j}:text"><div class="mv-row"><input type="number" step=".01" value="${w.start.toFixed(2)}" aria-label="字起点" data-word="${i}:${j}:start"><input type="number" step=".01" value="${w.end.toFixed(2)}" aria-label="字终点" data-word="${i}:${j}:end"></div></div>`).join('')}</div></details></td><td><input type="number" step=".01" data-time="${i}:start" value="${r.start.toFixed(2)}" aria-label="句起点"></td><td><input type="number" step=".01" data-time="${i}:end" value="${r.end.toFixed(2)}" aria-label="句终点"></td><td><label class="mv-check review"><input type="checkbox" data-review="${i}" ${r.review?'':'checked'}>${r.review?'待核对':'已核对'}</label></td></tr>`).join('');
    $('mv-lyric-rows').querySelectorAll('[data-seek]').forEach(e=>e.onclick=()=>seek(project.lyrics[+e.dataset.seek].start,true));
    $('mv-lyric-rows').querySelectorAll('[data-review]').forEach(e=>e.onchange=()=>{project.lyrics[+e.dataset.review].review=!e.checked;});
    $('mv-lyric-rows').querySelectorAll('[data-text]').forEach(e=>e.onchange=()=>{const r=project.lyrics[+e.dataset.text];r.text=e.value;const chars=Array.from(e.value);r.words=chars.map((text,j)=>({text,start:r.start+(r.end-r.start)*j/chars.length,end:r.start+(r.end-r.start)*(j+1)/chars.length}));r.review=true;r.timing='edited / estimated-words';drawLyrics();});
    $('mv-lyric-rows').querySelectorAll('[data-time]').forEach(e=>e.onchange=()=>{const [i,key]=e.dataset.time.split(':');const r=project.lyrics[+i],oldStart=r.start,oldEnd=r.end;r[key]=+e.value;if(r.end>r.start){for(const w of r.words){w.start=r.start+(w.start-oldStart)/(oldEnd-oldStart)*(r.end-r.start);w.end=r.start+(w.end-oldStart)/(oldEnd-oldStart)*(r.end-r.start);}}r.review=true;drawLyrics();});
    $('mv-lyric-rows').querySelectorAll('[data-word]').forEach(e=>e.onchange=()=>{const [i,j,key]=e.dataset.word.split(':');const r=project.lyrics[+i];r.words[+j][key]=key==='text'?e.value:+e.value;if(key==='text'){r.text=r.words.map(w=>w.text).join('');$('mv-lyric-rows').querySelector(`[data-text="${i}"]`).value=r.text;}r.review=true;});
  }
  const clock=t=>`${Math.floor(t/60).toString().padStart(2,'0')}:${Math.floor(t%60).toString().padStart(2,'0')}`;
  function drawTimeline(){if(!project)return;$('mv-strip').innerHTML=project.clips.map((c,i)=>`<button class="mv-shot ${i===selected?'selected':''} ${c.fallback?'fallback':''}" data-shot="${i}" style="width:${Math.max(85,c.dur*17)}px">${c.locked?'🔒 ':''}${clock(c.at)} · ${c.dur.toFixed(1)}s<small>${esc(c.src.split(/[\\/]/).pop())}</small></button>`).join('');$('mv-strip').querySelectorAll('button').forEach(b=>b.onclick=()=>{selected=+b.dataset.shot;seek(project.clips[selected].at);showShot();drawTimeline();});}
  function showShot(){
    const c=project?.clips[selected];if(!c){$('mv-shot-editor').innerHTML='<small>先编排镜头，再进行精修。</small>';return;}
    const options=project.assets.map(a=>`<option value="${esc(a.path)}" ${a.path===c.src?'selected':''}>${esc(a.name)}</option>`).join('');
    $('mv-shot-editor').innerHTML=`<strong>镜头 ${selected+1}</strong><small>${esc(c.reason||'手动镜头')}</small><label class="mv-check"><input id="mv-lock" type="checkbox" ${c.locked?'checked':''}>锁定此镜头</label><fieldset ${c.locked?'disabled':''} style="border:0;padding:0;margin:0"><label>替换素材<select id="mv-shot-source">${options}</select></label><div class="mv-row"><label>素材入点<input id="mv-shot-start" type="number" min="0" step=".01" value="${c.start.toFixed(2)}"></label><label>镜头时长<input id="mv-shot-dur" type="number" min="1" step=".01" value="${c.dur.toFixed(2)}"></label></div><small>调整时长会从相邻未锁定镜头借用时间，保持歌曲长度。</small><label>构图水平中心</label><input id="mv-focal-x" type="range" min="0" max="1" step=".01" value="${c.focal_x??.5}"><label>构图垂直中心</label><input id="mv-focal-y" type="range" min="0" max="1" step=".01" value="${c.focal_y??.5}"><label>本镜头滤镜<select id="mv-shot-filter"><option value="inherit">跟随全局</option>${$('mv-filter').innerHTML}</select></label><label>本镜头歌词样式<select id="mv-shot-lyric"><option value="inherit">跟随全局</option>${$('mv-lyric-style').innerHTML}</select></label><button id="mv-apply-shot">应用镜头调整</button></fieldset>`;
    $('mv-shot-filter').value=c.filter||'inherit';$('mv-shot-lyric').value=c.lyric_style||'inherit';
    $('mv-lock').onchange=()=>{c.locked=$('mv-lock').checked;drawTimeline();showShot();};
    $('mv-apply-shot').onclick=action(async()=>{
      const duration=+$('mv-shot-dur').value,delta=duration-c.dur;const neighbor=project.clips[selected+1]||project.clips[selected-1];
      if(Math.abs(delta)>.001&&(!neighbor||neighbor.locked||neighbor.dur-delta<1))throw new Error('相邻镜头已锁定或剩余不足 1 秒，无法分配时长');
      if(Math.abs(delta)>.001)neighbor.dur-=delta;
      Object.assign(c,{src:$('mv-shot-source').value,start:+$('mv-shot-start').value,dur:duration,focal_x:+$('mv-focal-x').value,focal_y:+$('mv-focal-y').value,filter:$('mv-shot-filter').value,lyric_style:$('mv-shot-lyric').value});
      let at=project.range[0];for(const clip of project.clips){clip.at=at;at+=clip.dur;}
      drawTimeline();seek(c.at);await saveProject();status('镜头已保存；重新生成粗剪查看实际构图与滤镜。');
    });
  }
  function drawRecs(){$('mv-recs').innerHTML=project.recommendations.map((r,i)=>`<button data-rec="${i}">${clock(r.start)}—${clock(r.end)}<small>${esc(r.label)}</small></button>`).join('');$('mv-recs').querySelectorAll('button').forEach(b=>b.onclick=()=>{const r=project.recommendations[+b.dataset.rec];$('mv-range-mode').value='highlight';$('mv-range-start').value=r.start;$('mv-range-end').value=r.end;seek(r.start,true);status('已试听推荐段落；点击“应用范围”后制作。');});}
  $('mv-apply-range').onclick=action(async()=>{if(!project)throw new Error('请先分析歌曲');const full=$('mv-range-mode').value==='full',start=full?0:+$('mv-range-start').value,end=full?project.duration:+$('mv-range-end').value;if(start<0||end>project.duration+.001||end-start<1)throw new Error('请选择歌曲内至少 1 秒的范围');if(project.clips.some(c=>c.locked)&&!confirm('切换制作范围需要重新编排镜头，包含已锁定镜头。继续吗？'))return;project.range=[start,end];project.clips=[];await saveProject();showProject();});
  $('mv-range-mode').onchange=()=>{if(project&&$('mv-range-mode').value==='full'){$('mv-range-start').value=0;$('mv-range-end').value=project.duration.toFixed(2);}};
  function drawHistory(){$('mv-history').innerHTML=project.renders.map((r,i)=>`<a href="/api/mv/projects/${project.id}/media?kind=render&index=${i}" target="_blank" rel="noopener">${r.preview?'低清粗剪 · 仅供校时':'高清正式'} · ${r.aspect} · ${new Date(r.created*1000).toLocaleTimeString()}</a><button data-render="${i}">在画布播放</button>`).join('');$('mv-history').querySelectorAll('button').forEach(b=>b.onclick=()=>playRender(+b.dataset.render));}
  function playRender(i){rendered=true;$('mv-audio').pause();$('mv-image').hidden=true;$('mv-overlay').hidden=true;const v=$('mv-video');v.src='/api/mv/projects/'+project.id+'/media?kind=render&index='+i;v.hidden=false;v.controls=true;v.muted=false;v.style.objectFit='contain';v.style.aspectRatio='auto';$('mv-preview-note').textContent='当前播放已生成版本；后续编辑需重新生成粗剪才能反映。';}
  function seek(t,play=false){rendered=false;$('mv-video').pause();$('mv-video').hidden=true;$('mv-audio').currentTime=Math.max(0,t);if(project){const found=project.clips.findIndex(c=>c.at<=t&&c.at+c.dur>t);if(found>=0&&selected!==found){selected=found;showShot();drawTimeline();}showFrame(t);}updateLyrics();if(play)$('mv-audio').play().catch(()=>{});}
  function showFrame(t){if(!project||rendered)return;const c=project.clips.find(c=>c.at<=t&&c.at+c.dur>t);if(!c)return;const i=project.assets.findIndex(a=>a.path===c.src),a=project.assets[i];if(!a)return;const src='/api/mv/projects/'+project.id+'/media?kind=asset&index='+i;
    const image=$('mv-image'),video=$('mv-video');image.hidden=!a.image;video.hidden=a.image;video.controls=false;video.muted=true;
    const element=a.image?image:video;if(element.getAttribute('src')!==src)element.src=src;
    element.style.objectFit='cover';element.style.aspectRatio=$('mv-aspect').value.replace(':','/');element.style.objectPosition=`${(c.focal_x??.5)*100}% ${(c.focal_y??.5)*100}%`;
    if(!a.image&&Math.abs(video.currentTime-(c.start+t-c.at))>.4){try{video.currentTime=c.start+t-c.at;}catch{}}
  }
  let activeLyricRow=-1;
  function updateLyrics(){if(!project||rendered)return;const t=$('mv-audio').currentTime,s=settings(),index=project.lyrics.findIndex(r=>r.start<=t&&r.end>t),r=project.lyrics[index],el=$('mv-overlay');el.hidden=!r;
    $('mv-clock').textContent=clock(t)+' / '+clock(project.duration);$('mv-seek').value=t;$('mv-size-label').textContent=(s.font_size*100).toFixed(1)+'%';
    if(r){el.style.top=(s.lyric_y*100)+'%';el.style.color=s.color;el.style.fontSize=Math.max(12,$('mv-stage').clientHeight*s.font_size)+'px';let content=esc(r.text);
      if(s.lyric_style==='karaoke')content=(r.words||[]).map(w=>`<span style="color:${t>=w.start?s.highlight:s.color}">${esc(w.text)}</span>`).join('');
      if(s.lyric_style==='scroll')content=`<div class="neighbor">${esc(project.lyrics[index-1]?.text||'')}</div><div style="color:${s.highlight}">${content}</div><div class="neighbor">${esc(project.lyrics[index+1]?.text||'')}</div>`;
      el.innerHTML=`<div style="background:rgba(0,0,0,${s.mask})">${content}</div>`;}
    if(index!==activeLyricRow){const rows=$('mv-lyric-rows').children;if(rows[activeLyricRow])rows[activeLyricRow].classList.remove('active');if(rows[index])rows[index].classList.add('active');activeLyricRow=index;}showFrame(t);drawWave();
  }
  function drawWave(){const canvas=$('mv-wave'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,65);if(!project)return;const values=project.waveform||[];ctx.fillStyle='#647f55';values.forEach((v,i)=>ctx.fillRect(i/values.length*canvas.width,32-v*27,Math.max(1,canvas.width/values.length-1),Math.max(2,v*54)));ctx.fillStyle='#d5f6b2';ctx.fillRect($('mv-audio').currentTime/project.duration*canvas.width,0,2,65);}
  $('mv-audio').ontimeupdate=updateLyrics;$('mv-seek').oninput=()=>seek(+$('mv-seek').value);$('mv-wave').onclick=e=>{if(project){const r=e.currentTarget.getBoundingClientRect();seek((e.clientX-r.left)/r.width*project.duration);}};
  $('mv-edit-view').onclick=()=>seek($('mv-audio').currentTime);
  for(const id of ['mv-size','mv-color','mv-highlight','mv-y','mv-mask','mv-lyric-style','mv-aspect'])$(id).addEventListener('input',updateLyrics);
  let sceneNames=[];
  Promise.all([studioMetadata(),api('/capabilities')]).then(([meta,caps])=>{$('mv-filter').innerHTML=meta.filters.map(f=>`<option value="${f.id}">${esc(f.label)}</option>`).join('');$('mv-filter').value='warm';$('mv-font').innerHTML=meta.fonts.map(f=>`<option value="${esc(f.path)}">${esc(f.label)}</option>`).join('');$('mv-out').placeholder=meta.default_output;sceneNames=caps.scenes;if(!caps.asr)status('本版本未安装识别引擎，可先使用 LRC；请安装带 MV 引擎的版本。');}).catch(e=>status(e.message,true));
})();
