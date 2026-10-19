/* Program Flow: browser holds only an httpOnly profile cookie, never API keys. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const sessionMeta = {
    NXT_AM: {label:'NXT 오전', market:'NXT', start:480, end:539},
    KRX: {label:'KRX 정규장', market:'KRX', start:540, end:930},
    NXT_PM: {label:'NXT 오후', market:'NXT', start:930, end:1200}
  };
  let current = null, selected = 'NXT_AM', filter = 'ALL', ready = false, hasKeys = false, tokenError = null, busy = false, resolved = null;
  let searchTimer = null, searchSerial = 0, suggestions = [], activeSuggestion = -1, pendingLoad = null, inputNeedsSelection = false, liveDate = true;
  let retryTimer = null, retryAttempt = 0, booting = false, waiting = false, needsReconnect = false, sessionExplicit = false, monitorBusy = false, watchedCode = null;
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  $('trade-date').value = today();
  $('trade-date').max = today();
  const ymd = () => $('trade-date').value.replaceAll('-','');
  const name = () => $('stock-name').value.trim();
  const amount = value => value == null ? '—' : `${(value / 1e8).toLocaleString('ko-KR', {minimumFractionDigits:1, maximumFractionDigits:1})}억`;
  const clock = tm => tm ? `${tm.slice(0,2)}:${tm.slice(2,4)}:${tm.slice(4,6)}` : '—';
  const minutes = tm => Number(tm.slice(0,2))*60 + Number(tm.slice(2,4)) + Number(tm.slice(4,6))/60;
  const posneg = (el, value) => { el.classList.toggle('positive', value > 0); el.classList.toggle('negative', value < 0); };
  function showMessage(message, error=false) { $('message').textContent = message; $('message').classList.toggle('hidden', !message); $('message').classList.toggle('error', error); }
  function status(message, loading=false) {
    $('status').textContent = message;
    const box = $('status').closest('.toolbar-status');
    box.classList.toggle('busy', loading);
    box.dataset.state = /실패|필요/.test(message) ? 'error' : hasKeys && !tokenError ? 'connected' : 'idle';
  }
  async function api(path, opts={}) {
    const response = await fetch(path, {credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(180000), headers:{'Content-Type':'application/json'}, ...opts});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    return body;
  }
  let settingsReturnFocus = null;
  function settings(show) {
    const screen = $('settings-screen');
    if (show && !screen.classList.contains('hidden')) return;
    screen.classList.toggle('hidden', !show);
    $('settings-error').textContent = '';
    document.body.classList.toggle('modal-open', show);
    document.querySelector('.shell').inert = show;
    if (show) {
      settingsReturnFocus = document.activeElement;
      screen.querySelector('.modal').focus();
    } else {
      $('app-key').value=''; $('app-secret').value='';
      if (settingsReturnFocus && settingsReturnFocus !== document.body) settingsReturnFocus.focus();
      else $('settings-btn').focus();
    }
  }
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    $('theme-btn').setAttribute('aria-label', theme === 'dark' ? '라이트 모드로 전환' : '다크 모드로 전환');
    $('theme-btn').setAttribute('aria-pressed', String(theme === 'dark'));
    document.querySelector('meta[name="theme-color"]').content = theme === 'dark' ? '#13171f' : '#f7f8fa';
  }
  try { setTheme(localStorage.getItem('program-flow-theme') === 'dark' ? 'dark' : 'light'); } catch { setTheme('light'); }
  $('theme-btn').addEventListener('click', () => {
    const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    setTheme(theme);
    try { localStorage.setItem('program-flow-theme', theme); } catch { /* Theme works without storage. */ }
  });
  document.querySelectorAll('[data-open-settings]').forEach(button => button.addEventListener('click', () => settings(true)));
  $('settings-screen').addEventListener('click', event => { if (event.target === $('settings-screen')) settings(false); });
  $('settings-screen').addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const focusable = [...$('settings-screen').querySelectorAll('button,a[href],input')].filter(el => !el.disabled);
    const first = focusable[0], last = focusable.at(-1);
    if (event.shiftKey && (document.activeElement === first || document.activeElement === $('settings-screen').querySelector('.modal'))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  function hideSuggestions() {
    $('stock-suggestions').classList.add('hidden');
    $('stock-name').setAttribute('aria-expanded', 'false');
    $('stock-name').removeAttribute('aria-activedescendant');
    activeSuggestion = -1;
  }
  function highlightSuggestion(index) {
    activeSuggestion = index;
    [...$('stock-suggestions').querySelectorAll('.stock-option')].forEach((option, i) => {
      option.classList.toggle('active', i === index);
      option.setAttribute('aria-selected', String(i === index));
      if (i === index) option.scrollIntoView?.({block:'nearest'});
    });
    if (index >= 0) $('stock-name').setAttribute('aria-activedescendant', `stock-option-${index}`);
    else $('stock-name').removeAttribute('aria-activedescendant');
  }
  function showSuggestions(items, hasMore=false, message='') {
    suggestions = items;
    const box = $('stock-suggestions'); box.replaceChildren();
    items.forEach((item, i) => {
      const button = document.createElement('button');
      button.type = 'button'; button.id = `stock-option-${i}`;
      button.className = 'stock-option'; button.setAttribute('role','option');
      button.setAttribute('aria-selected','false');
      const label = document.createElement('span'); label.textContent = item.name;
      const code = document.createElement('span'); code.className = 'stock-option-code'; code.textContent = item.code;
      button.append(label,code);
      button.addEventListener('click', () => chooseSuggestion(item));
      box.append(button);
    });
    if (hasMore || !items.length || message) {
      const note = document.createElement('div'); note.className = 'stock-search-note';
      note.textContent = message || (hasMore ? '추가 결과가 있습니다. 검색어를 더 입력하세요.' : '일치하는 종목이 없습니다.');
      box.append(note);
    }
    activeSuggestion = -1;
    $('stock-name').removeAttribute('aria-activedescendant');
    box.classList.remove('hidden');
    $('stock-name').setAttribute('aria-expanded','true');
  }
  function chooseSuggestion(item) {
    clearTimeout(searchTimer); clearTimeout(retryTimer);retryTimer=null; retryAttempt=0; searchSerial++; sessionExplicit=false;
    $('stock-name').value = item.name;
    resolved = {query:item.name, name:item.name, code:item.code};
    inputNeedsSelection = false;
    hideSuggestions(); showMessage('');
    load('select');
  }
  function scheduleStockSearch() {
    clearTimeout(retryTimer);retryTimer=null;
    resolved = null;
    inputNeedsSelection = true;
    const query = name(), serial = ++searchSerial;
    clearTimeout(searchTimer);
    hideSuggestions();
    if (!query) return;
    searchTimer = setTimeout(async () => {
      try {
        const found = await api(`/api/stocks/search?q=${encodeURIComponent(query)}`);
        if (serial !== searchSerial || name() !== query) return;
        showSuggestions(found.items, found.has_more);
      } catch (error) {
        if (serial !== searchSerial || name() !== query) return;
        showSuggestions([], false, error.message);
      }
    }, 180);
  }
  function hasData() { return Boolean(current?.rows?.length); }
  function showLoading(title='프로그램 매매 데이터를 불러오고 있습니다', detail='키움에서 데이터를 받는 중입니다. 잠시만 기다려 주세요.') {
    if (hasData() && current.sessions[selected]?.points.length) return;
    const chart=$('chart'); chart.replaceChildren(); chart.setAttribute('aria-busy','true');
    const box=document.createElement('div'); box.className='empty-state loading-state';box.setAttribute('role','status');
    const graphic=svg('svg',{viewBox:'0 0 160 90',class:'loading-graphic','aria-hidden':'true'});
    for (const y of [20,45,70]) graphic.append(svg('path',{d:`M10 ${y}H150`,class:'loading-grid'}));
    graphic.append(svg('path',{d:'M12 67 35 53 54 61 77 32 98 42 121 19 148 26',class:'loading-trend'}));
    const pulse=svg('circle',{cx:148,cy:26,r:5,class:'loading-pulse'});graphic.append(pulse);
    const heading=document.createElement('strong');heading.textContent=title;
    const help=document.createElement('small');help.textContent=detail;
    const activity=document.createElement('span');activity.className='loading-dots';activity.setAttribute('aria-hidden','true');
    for(let i=0;i<3;i++)activity.append(document.createElement('i'));
    box.append(graphic,heading,help,activity);chart.append(box);
  }
  function scheduleRetry(error=null, bootstrap=false) {
    clearTimeout(retryTimer);retryTimer=null;
    const seconds=Math.min(30,5*2**Math.min(retryAttempt++,3));
    waiting=true;
    status(`${seconds}초 후 자동으로 다시 연결합니다`,true);
    showMessage(error ? `${error.message} ${seconds}초 후 자동으로 다시 시도합니다.` : '아직 수신된 데이터가 없습니다. 자동으로 다시 확인합니다.',Boolean(error));
    if(!hasData())showLoading(error?'연결을 다시 확인하고 있습니다':'첫 데이터를 기다리고 있습니다',`${seconds}초 후 자동으로 다시 시도합니다. 이 화면을 그대로 두세요.`);
    retryTimer=setTimeout(()=>{retryTimer=null;bootstrap?boot():load('retry');},seconds*1000);
  }
  async function boot() {
    if(booting)return;
    booting=true;waiting=true;
    status('저장된 연결을 확인하는 중…',true);showLoading('키움 연결을 확인하고 있습니다');
    try {
      const session=await api('/api/session',{method:'POST'});
      ready=true;hasKeys=session.has_keys;tokenError=session.token_error;needsReconnect=Boolean(tokenError);
      const saved=await api('/api/watch');
      if(saved.watch){watchedCode=saved.watch.code;resolved={query:saved.watch.name,name:saved.watch.name,code:saved.watch.code};$('stock-name').value=saved.watch.name;}
      await load(saved.watch?'startup':'select');
    } catch(error) { ready=false;scheduleRetry(error,true); }
    finally { booting=false; }
  }
  async function load(mode='poll') {
    if(!ready){await boot();return;}
    if(busy){if(mode!=='poll')pendingLoad=mode;return;}
    const query = name(), date = ymd();
    if(!query||query.length>80||!/^\d{8}$/.test(date)){showMessage('종목명과 거래일을 확인하세요.',true);return;}
    if(inputNeedsSelection){if(mode!=='poll')showMessage('검색 결과에서 종목을 클릭해 선택하세요.',true);return;}
    if(!hasKeys){waiting=false;status('API 키를 등록하면 종목명을 조회합니다');chartEmpty('API 키를 연결해 주세요');settings(true);return;}
    clearTimeout(retryTimer);retryTimer=null;busy=true;waiting=true;
    if(current && (current.date!==date || (resolved && current.code!==resolved.code)))current=null;
    if(!hasData())showLoading();
    showMessage('');status('저장된 데이터 읽는 중…',true);
    try {
      if(needsReconnect){
        status('인증 토큰을 새로 발급하는 중…',true);
        if(!hasData())showLoading('키움 연결을 다시 갱신하고 있습니다','저장된 API 키로 인증 토큰을 새로 발급합니다.');
        await api('/api/reconnect',{method:'POST'});tokenError=null;needsReconnect=false;
      }
      if(!resolved||resolved.query!==query){
        current=null;
        showLoading('종목명을 확인하고 있습니다');
        const match=await api(`/api/stocks/resolve?name=${encodeURIComponent(query)}`);
        if(name()!==query||ymd()!==date)return;
        if(!/^\d{6}$/.test(match.code)||!match.name)throw new Error('키움 종목코드 응답 오류');
        resolved={query,code:match.code,name:match.name};
        mode='select';
      }
      const code=resolved.code;
      const isCurrent=()=>name()===query&&ymd()===date&&resolved?.code===code;
      current=await api(`/api/data?code=${encodeURIComponent(code)}&date=${date}`);
      if(!isCurrent()){current=null;return;}
      render();
      if(mode==='select'||watchedCode!==code){
        status('선택한 종목의 데이터를 수집하는 중…',true);
        const watched=await api('/api/watch',{method:'POST',body:JSON.stringify({code,name:resolved.name})});
        watchedCode=code;
        if(!isCurrent())return;
        if(date===today().replaceAll('-','')){current=watched.result.data;render();}
      }
      if(mode==='startup'||mode==='retry'||(mode!=='poll'&&date!==today().replaceAll('-',''))){
        status('키움에서 최신 데이터를 수집하는 중…',true);
        const result=await api('/api/sync',{method:'POST',body:JSON.stringify({code,date,force:mode==='startup'||mode==='retry'})});
        if(!isCurrent())return;
        current=result.data;render();
      }
      const watch=await api('/api/watch');
      if(!isCurrent())return;
      if(watch.last_error)throw new Error(watch.last_error);
      tokenError=null;needsReconnect=false;waiting=false;
      if(!hasData()&&date===today().replaceAll('-','')){scheduleRetry();return;}
      retryAttempt=0;showMessage('');status('자동 수집 중 · 화면은 분마다 갱신');drawChart();
    } catch(error) {
      needsReconnect=true;tokenError=error.message;scheduleRetry(error);
    } finally {
      busy=false;
      if(pendingLoad){const next=pendingLoad;pendingLoad=null;queueMicrotask(()=>load(next));}
    }
  }
  // Read saved progress while an upstream query is pending; this makes a completed
  // market visible without waiting for the other market's pagination to finish.
  setInterval(async()=>{
    if(!busy||!waiting||!resolved||monitorBusy)return;
    monitorBusy=true;
    const code=resolved.code,date=ymd();
    try{
      const watch=await api('/api/watch');
      const market=watch.progress?.market;
      if(watch.progress?.state==='collecting'&&watch.progress.code===code&&watch.progress.date===date){
        status(`${market} 데이터를 수집하는 중…`,true);
        if(!hasData())showLoading(`${market} 데이터를 불러오고 있습니다`,'전체 페이지를 확인한 뒤 차트에 표시합니다.');
      }
      const saved=await api(`/api/data?code=${encodeURIComponent(code)}&date=${date}`);
      if(resolved?.code===code&&ymd()===date&&saved.rows.length){current=saved;render();}
    }catch{/* The main request owns recovery and the visible error message. */}
    finally{monitorBusy=false;}
  },3000);
  function render() {
    if (!current) return;
    $('display-date').textContent = `${current.date.slice(0,4)}.${current.date.slice(4,6)}.${current.date.slice(6,8)} · ${resolved.name} (${current.code})`;
    const ids = {NXT_AM:'total-nxt-am',KRX:'total-krx',NXT_PM:'total-nxt-pm'};
    for (const [key,id] of Object.entries(ids)) {
      const el = $(id), value = current.sessions[key].latest;
      el.textContent = amount(value); posneg(el,value);
      el.title = value == null ? current.sessions[key].reason : '';
    }
    const fmtSync = ts => ts ? new Date(ts*1000).toLocaleTimeString('ko-KR',{hour:'2-digit',minute:'2-digit'}) : '미수집';
    $('sync-note').textContent = `KRX ${fmtSync(current.synced_at.KRX)} · NXT ${fmtSync(current.synced_at.NXT)}`;
    $('stock-code-label').textContent = current.code;
    document.querySelectorAll('[data-spark]').forEach(box => {
      box.replaceChildren();
      const points = current.sessions[box.dataset.spark].points;
      if (points.length < 2) return;
      const values = points.map(point => point.net_amt);
      const low = Math.min(...values), range = Math.max(Math.max(...values)-low, 1);
      const graphic = svg('svg', {viewBox:'0 0 80 30', preserveAspectRatio:'none'});
      const line = points.map((point,i) => `${i?'L':'M'}${i/(points.length-1)*80},${27-(point.net_amt-low)/range*24}`).join(' ');
      graphic.append(svg('path', {d:line, fill:'none', stroke:'currentColor', 'stroke-width':1.7, 'stroke-linejoin':'round'}));
      box.append(graphic);
    });
    if(!sessionExplicit && !current.sessions[selected].points.length){
      const available=['KRX','NXT_AM','NXT_PM'].find(key=>current.sessions[key].points.length);
      if(available)selectSession(available);
    }
    drawChart(); drawRows();
  }
  function svg(name, attributes={}) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key,val] of Object.entries(attributes)) element.setAttribute(key, String(val));
    return element;
  }
  function chartEmpty(text) {
    const box = $('chart'); box.replaceChildren(); box.setAttribute('aria-busy','false');
    const div = document.createElement('div'); div.className='empty-state';
    const symbol = document.createElement('span'); symbol.className = 'empty-icon';
    const graphic = svg('svg', {viewBox:'0 0 24 24', fill:'none', stroke:'currentColor', 'stroke-width':1.5, class:'icon'});
    graphic.append(svg('path', {d:'M2 12h5l3-8 4 16 3-8h5', 'stroke-linecap':'round', 'stroke-linejoin':'round'}));
    symbol.append(graphic);
    const title = document.createElement('strong'); title.textContent=text;
    const help = document.createElement('small'); help.textContent = hasKeys ? '선택한 종목·거래일의 관측값을 확인합니다. 관측되지 않은 분은 채우지 않습니다.' : '오른쪽 위 설정에서 API 키를 연결해 주세요.';
    div.append(symbol,title,help); box.append(div);
  }
  function drawChart() {
    const meta = sessionMeta[selected], series = current.sessions[selected];
    $('chart-title').textContent = `${meta.label} · 누적 순매수 대금`;
    $('chart-note').textContent = series.reason || '관측된 시각만 연결하며 빈 분은 임의로 채우지 않습니다.';
    if (!series.points.length) { if(waiting){showLoading();}else{chartEmpty(series.reason || '해당 세션 데이터가 없습니다');} return; }
    const points = series.points.map(({tm,net_amt}) => ({tm,net:net_amt}));
    if (!points.length) { chartEmpty('해당 세션 데이터가 없습니다'); return; }
    const chart = $('chart'); chart.replaceChildren(); chart.setAttribute('aria-busy','false');
    const chartStyle = getComputedStyle(chart);
    const width = Math.max(260, chart.clientWidth-parseFloat(chartStyle.paddingLeft)-parseFloat(chartStyle.paddingRight));
    const plotLeft = width < 500 ? 44 : 58, plotRight = width-16, plotWidth = plotRight-plotLeft;
    const graphic = svg('svg',{viewBox:`0 0 ${width} 300`,preserveAspectRatio:'none','aria-label':`${meta.label} 순매수 차트`});
    const defs=svg('defs'), gradient=svg('linearGradient',{id:'areaFade',x1:'0',x2:'0',y1:'0',y2:'1'});
    gradient.append(svg('stop',{offset:'0%','stop-color':'var(--accent)','stop-opacity':'.12'}),svg('stop',{offset:'100%','stop-color':'var(--accent)','stop-opacity':'0'})); defs.append(gradient); graphic.append(defs);
    const vals = points.map(p => p.net);
    const min = Math.min(0,...vals), max=Math.max(0,...vals), range=Math.max(max-min,1);
    const x = tm => plotLeft + (minutes(tm)-meta.start)/Math.max(meta.end-meta.start,1)*plotWidth;
    const y = value => 18 + (max-value)/range*240;
    for (let i=0;i<=4;i++) {
      const value=max - range*i/4, ypos=y(value);
      graphic.append(svg('line',{x1:plotLeft,y1:ypos,x2:plotRight,y2:ypos,class:value===0?'zero':'grid'}));
      const label=svg('text',{x:plotLeft-10,y:ypos+4,'text-anchor':'end',class:'axis'}); label.textContent=amount(value); graphic.append(label);
    }
    const zero=y(0), first=points[0], last=points.at(-1);
    const path = field => points.map((p,i)=>`${i?'L':'M'}${x(p.tm).toFixed(1)},${y(p[field]).toFixed(1)}`).join(' ');
    graphic.append(svg('path',{d:`${path('net')} L${x(last.tm)},${zero} L${x(first.tm)},${zero} Z`,class:'area'}));
    graphic.append(svg('path',{d:path('net'),class:'net-line'}));
    for (const p of [...new Set([first,points[Math.floor(points.length/2)],last])]) {
      const label=svg('text',{x:x(p.tm),y:289,'text-anchor':p===first?'start':p===last?'end':'middle',class:'axis'});
      label.textContent=clock(p.tm).slice(0,5);graphic.append(label);
    }
    for (const p of points) {
      const dot=svg('circle',{cx:x(p.tm),cy:y(p.net),r:3.5,class:p===last?'last-dot':'data-dot'});
      const tip=svg('title');tip.textContent=`${clock(p.tm)} · 순매수 누적 ${amount(p.net)}`;
      dot.append(tip);graphic.append(dot);
    }
    const crosshair = svg('line', {x1:plotLeft, x2:plotLeft, y1:18, y2:258, class:'crosshair hidden'});
    graphic.append(crosshair);
    const tooltip = document.createElement('div'); tooltip.className='chart-tooltip hidden'; tooltip.setAttribute('aria-hidden', 'true');
    const tipTime=document.createElement('span'), tipValue=document.createElement('strong'); tooltip.append(tipTime,tipValue);
    const hitArea = svg('rect',{x:plotLeft,y:18,width:plotWidth,height:240,class:'hit-area'});
    hitArea.addEventListener('pointermove', event => {
      const rect=graphic.getBoundingClientRect(), px=(event.clientX-rect.left)/rect.width*width;
      const point=points.reduce((best, p) => Math.abs(x(p.tm)-px)<Math.abs(x(best.tm)-px) ? p : best, points[0]);
      crosshair.classList.remove('hidden'); crosshair.setAttribute('x1',x(point.tm)); crosshair.setAttribute('x2',x(point.tm));
      tipTime.textContent=`${meta.label}  ${clock(point.tm)}`;tipValue.textContent=`순매수 누적 ${amount(point.net)}`;
      tooltip.classList.remove('hidden');
      const box=chart.getBoundingClientRect();
      tooltip.style.left=`${Math.max(8,Math.min(event.clientX-box.left+14,box.width-tooltip.offsetWidth-8))}px`;
      tooltip.style.top=`${Math.max(10,Math.min(event.clientY-box.top-65,box.height-70))}px`;
    });
    hitArea.addEventListener('pointerleave', () => { crosshair.classList.add('hidden'); tooltip.classList.add('hidden'); });
    graphic.append(hitArea);
    chart.append(tooltip);
    chart.append(graphic);
  }
  function drawRows() {
    const rows = current.rows.filter(row => filter==='ALL' || row.market===filter).slice().reverse();
    $('row-count').textContent=`${rows.length.toLocaleString()}건`;
    const body=$('rows'); body.replaceChildren();
    if (!rows.length) {const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.className='empty-table';td.textContent='이 날짜에 저장된 관측 데이터가 없습니다.';tr.append(td);body.append(tr);return;}
    for (const row of rows) {
      const tr=document.createElement('tr');
      const values=[clock(row.tm),row.market,amount(row.buy_amt),amount(row.sell_amt),amount(row.net_amt)];
      values.forEach((v,i)=>{const td=document.createElement('td');if(i>=2)td.classList.add('numeric');if(i===4)posneg(td,row.net_amt);if(i===1){const span=document.createElement('span');span.className=`market-label ${row.market==='KRX'?'krx':''}`;span.textContent=v;td.append(span);}else td.textContent=v;tr.append(td);});body.append(tr);
    }
  }
  function selectSession(key){
    selected=key;
    document.querySelectorAll('.session-card').forEach(button=>{
      const active=button.dataset.session===key;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));
      button.querySelector('.session-select-label').firstChild.textContent=active?'선택한 구간 ':'차트 보기 ';
    });
  }
  document.querySelectorAll('.session-card').forEach(button=>button.addEventListener('click',()=>{sessionExplicit=true;selectSession(button.dataset.session);if(current)drawChart();}));
  document.querySelectorAll('.filter').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;document.querySelectorAll('.filter').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-pressed',String(b===button));});if(current)drawRows();}));
  $('stock-name').addEventListener('input', scheduleStockSearch);
  $('stock-name').addEventListener('keydown',event=>{
    if (event.key === 'Escape') { hideSuggestions(); return; }
    if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && !$('stock-suggestions').classList.contains('hidden') && suggestions.length) {
      event.preventDefault();
      highlightSuggestion((activeSuggestion + (event.key === 'ArrowDown' ? 1 : -1) + suggestions.length) % suggestions.length);
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (!$('stock-suggestions').classList.contains('hidden') && suggestions.length) {
        if (activeSuggestion < 0) { showMessage('검색 결과에서 종목을 클릭하거나 방향키로 선택하세요.', true); return; }
        chooseSuggestion(suggestions[activeSuggestion]);
      } else if (resolved && !inputNeedsSelection) load('select');
    }
  });
  document.addEventListener('pointerdown',event=>{if (!event.target.closest('.stock-search')) hideSuggestions();});
  $('trade-date').addEventListener('change',()=>{ liveDate = ymd() === today().replaceAll('-',''); load('date'); });
  $('settings-btn').addEventListener('click',()=>settings(true));$('settings-close').addEventListener('click',()=>settings(false));
  $('keys-form').addEventListener('submit',async event=>{event.preventDefault();$('settings-error').textContent='';try{await api('/api/keys',{method:'POST',body:JSON.stringify({app_key:$('app-key').value.trim(),app_secret:$('app-secret').value.trim()})});hasKeys=true;tokenError=null;needsReconnect=false;retryAttempt=0;clearTimeout(retryTimer);retryTimer=null;settings(false);showMessage('키움 연결을 확인했습니다. 자동 수집을 시작합니다.');await load('select');}catch(error){$('settings-error').textContent=error.message;}});
  $('delete-keys').addEventListener('click',async()=>{if(!confirm('저장된 API 키를 삭제하시겠습니까? 저장된 분봉은 유지됩니다.'))return;try{await api('/api/keys',{method:'DELETE'});hasKeys=false;tokenError=null;needsReconnect=false;waiting=false;clearTimeout(retryTimer);retryTimer=null;resolved=null;current=null;chartEmpty('API 키를 등록하면 종목명을 조회합니다');settings(false);showMessage('API 키를 삭제했습니다.');}catch(error){$('settings-error').textContent=error.message;}});
  document.addEventListener('keydown',event=>{if(event.key==='Escape' && !$('settings-screen').classList.contains('hidden'))settings(false);});
  function refreshSaved() {
    if (liveDate && ymd() !== today().replaceAll('-','')) { $('trade-date').value = today(); $('trade-date').max = today(); }
    if(!ready){boot();return;}
    if(hasKeys&&!retryTimer)load('poll');
  }
  setInterval(refreshSaved,60000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshSaved();});
  if('serviceWorker' in navigator)navigator.serviceWorker.register('/service-worker.js').catch(()=>{});
  let previousChartWidth = 0;
  new ResizeObserver(entries => {
    const width = Math.round(entries[0].contentRect.width);
    if (width !== previousChartWidth) { previousChartWidth = width; if (current) requestAnimationFrame(drawChart); }
  }).observe($('chart'));
  boot();
})();
