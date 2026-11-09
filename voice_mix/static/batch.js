/* Explicit separators take precedence over numbered headings, then blank paragraphs. */
(function(scope){
  function splitScripts(text, mode='auto') {
    text=String(text||'').replace(/\r\n?/g,'\n').trim();if(!text)return [];
    const divider=/^\s*(?:-{3,}|={3,}|\*{3,})\s*$/m;
    const heading=/^\s*(?:(?:文案\s*\d+|第\s*\d+\s*[条篇则](?:文案)?)[：:、.．]?|【\s*(?:文案\s*)?\d+\s*】|\d{1,3}[、.．)）](?!\d))\s*/gm;
    let parts;
    if(mode==='line')parts=text.split('\n');
    else if(mode==='blank')parts=text.split(/\n\s*\n+/);
    else if(mode==='divider'||divider.test(text))parts=text.split(new RegExp(divider.source,'gm'));
    else if([...text.matchAll(heading)].length>=2){
      const marks=[...text.matchAll(heading)];parts=[];
      if(text.slice(0,marks[0].index).trim())parts.push(text.slice(0,marks[0].index));
      marks.forEach((m,i)=>parts.push(text.slice(m.index+m[0].length,marks[i+1]?.index??text.length)));
    }else parts=text.split(/\n\s*\n+/);
    return parts.map(s=>s.trim()).filter(Boolean);
  }
  if(typeof module!=='undefined')module.exports={splitScripts};
  if(typeof document==='undefined')return;
  scope.splitScripts=splitScripts;
  const script=document.getElementById('script');
  const box=document.createElement('div');
  box.innerHTML=`<label for="script-mode">文案任务模式</label><select id="script-mode"><option value="single">单文案 → 多条视频</option><option value="batch">多文案 → 批量视频</option></select><div id="batch-options" hidden><label for="script-split">批量粘贴识别方式</label><select id="script-split"><option value="auto">自动识别：分隔线 / 编号 / 空行</option><option value="blank">空行分隔（单条可含多行）</option><option value="line">每行一条文案</option><option value="divider">--- 分隔线</option></select><small>可粘贴“文案1：… 文案2：…”；边界不清楚时，在文案之间单独写一行 ---。编号内容也可能是同一文案的步骤，请检查识别列表。</small></div><div id="batch-summary" role="status" aria-live="polite"></div><details id="batch-preview" hidden><summary>检查已识别文案</summary><ol id="batch-list"></ol></details>`;
  script.before(box);
  const old=document.getElementById('count'),count=document.createElement('input');count.id='count';count.type='number';count.min=1;count.max=200;count.value=1;count.style.width='110px';old.replaceWith(count);
  count.before(document.createTextNode('每条文案生成 '));
  let updateTimer;
  function update(){clearTimeout(updateTimer);updateTimer=setTimeout(paintSummary,150);}
  function paintSummary(){
    const batch=document.getElementById('script-mode').value==='batch';
    const items=batch?splitScripts(script.value,document.getElementById('script-split').value):[script.value.trim()].filter(Boolean);
    document.getElementById('batch-options').hidden=!batch;document.getElementById('batch-preview').hidden=!batch;
    const n=Number(count.value),total=items.length*n;
    document.getElementById('batch-summary').textContent=`已识别 ${items.length} 条文案 × 每条 ${n||0} 个视频 = 共 ${Number.isFinite(total)?total:0} 个（单批最多 200 个）`;
    const list=document.getElementById('batch-list');list.replaceChildren();
    if(document.getElementById('batch-preview').open) items.slice(0,200).forEach(text=>{const li=document.createElement('li');li.textContent=text.length>800?text.slice(0,800)+'…（完整文案仍用于生成）':text;li.style.whiteSpace='pre-wrap';li.style.marginBottom='12px';list.append(li);});
    script.placeholder=batch?'文案1：第一条完整文案…\n\n文案2：第二条完整文案…\n\n或用单独一行 --- 分隔每条文案。':'输入一条完整文案，可包含多行。';
  }
  document.getElementById('batch-preview').addEventListener('toggle',update);
  for(const e of [script,count,document.getElementById('script-mode'),document.getElementById('script-split')]){e.addEventListener('input',update);e.addEventListener('change',update);}update();
})(typeof window==='undefined'?{}:window);
