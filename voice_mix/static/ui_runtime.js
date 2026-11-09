/* One metadata request for all panels; bound startup waits without touching renders. */
window.fetchWithTimeout = async function(url, timeout=10000) {
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeout);
  try { return await fetch(url,{signal:controller.signal}); }
  finally { clearTimeout(timer); }
};
window.studioMetadata = function() {
  if(!window._studioMeta) window._studioMeta=fetchWithTimeout('/api/voices').then(r=>{
    if(!r.ok)throw new Error('剪辑服务暂未就绪');return r.json();
  }).catch(error=>{window._studioMeta=null;throw error;});
  return window._studioMeta;
};

window.addEventListener('DOMContentLoaded',()=>{
  fetchWithTimeout('/api/health').then(r=>r.json()).then(meta=>{
    if(!meta.browser_mode)return;
    const bar=document.querySelector('.studio-status');
    if(!bar)return;
    const button=document.createElement('button');button.textContent='退出兼容工作台';
    button.onclick=async()=>{
      if(!confirm('结束本机工作台服务？请先保存项目并等待正在生成的任务完成。'))return;
      const response=await fetch('/api/desktop/exit',{method:'POST'});
      if(response.ok){button.disabled=true;button.textContent='已退出，可关闭此标签页';}
      else alert((await response.json()).detail||'退出失败');
    };
    bar.append(button);
  }).catch(()=>{});
});

// A server being ready is not the same as the editing interface being ready.
let pageReadinessSent=false;
function reportWorkbenchReady(){
  if(pageReadinessSent||document.readyState==='loading'||!window._studioInitialized||!document.querySelector('.studio')||!document.getElementById('script-mode')||!document.getElementById('mv-status'))return;
  pageReadinessSent=true;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{
    fetchWithTimeout('/api/health').then(r=>r.json()).then(meta=>fetch('/api/desktop/ready',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({instance:meta.instance})
    })).catch(()=>{pageReadinessSent=false;});
  }));
}
window.addEventListener('studio-ready',reportWorkbenchReady);
window.addEventListener('DOMContentLoaded',reportWorkbenchReady);
