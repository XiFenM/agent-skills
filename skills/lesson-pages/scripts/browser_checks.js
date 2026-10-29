/* Playwright run-code function. Inspect the current local lesson in fresh contexts;
   do not clear or change the reader's current page, history, theme or storage.
   Optional options: widths, themes, anchors, maxLandmarks, settleMs, screenshotDirectory. */
async (page, options = {}) => {
  const url = await page.evaluate(() => ({protocol:location.protocol, hostname:location.hostname, href:location.href.split('#')[0]}));
  const local = url.protocol === 'file:' || (['http:', 'https:'].includes(url.protocol) && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname));
  if (!local) throw new Error('Open the requested local lesson first; this checker does not navigate external sites.');
  const browser = page.context().browser();
  if (!browser) return {ok:false, issues:[{kind:'browser-unavailable', message:'The browser tool cannot create isolated contexts; use the manual reading checks.'}]};
  const widths = options.widths || [390, 768, 1280];
  const themes = options.themes || ['light', 'dark'];
  const settleMs = Math.max(900, options.settleMs || 1050);
  const maxLandmarks = options.maxLandmarks === undefined ? 4 : options.maxLandmarks;
  const runs = [], issues = [];
  for (const width of widths) {
    for (const theme of themes) {
      const context = await browser.newContext({viewport:{width, height:900}, colorScheme:theme, reducedMotion:'no-preference'});
      const current = await context.newPage();
      const errors = [];
      current.on('pageerror', error => errors.push(error.message));
      current.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()); });
      try {
        await current.goto(url.href, {waitUntil:'load', timeout:20000});
        await current.evaluate(async () => { if (document.fonts) await document.fonts.ready; });
        await current.waitForTimeout(settleMs);
        const inspect = () => current.evaluate(() => {
          const shown = el => !!el.getClientRects().length && el.getBoundingClientRect().height > 0;
          const rect = el => { const r=el.getBoundingClientRect(); return {left:r.left, right:r.right, top:r.top, bottom:r.bottom, width:r.width, height:r.height}; };
          const problems = [];
          const cover=document.querySelector('.lp-cover'), coverBottom=cover ? cover.getBoundingClientRect().bottom : 0;
          if (document.documentElement.scrollWidth > innerWidth + 1) problems.push({kind:'page-overflow', width:innerWidth, content:document.documentElement.scrollWidth});
          if (scrollY < 2 && coverBottom > 0) {
            for (const note of document.querySelectorAll('main .lp-note')) {
              if (shown(note) && note.getBoundingClientRect().top < coverBottom - 1) problems.push({kind:'note-on-cover', text:note.textContent.trim().slice(0,60)});
            }
          }
          for (const segment of document.querySelectorAll('.lp-seg')) {
            const active=segment.querySelector('button[aria-pressed="true"]'), thumb=segment.querySelector('.lp-seg-thumb');
            if (!active || !thumb || !shown(active) || !shown(thumb)) continue;
            const a=rect(active), t=rect(thumb);
            if (['left','top','width','height'].some(k=>Math.abs(a[k]-t[k])>2)) problems.push({kind:'selection-background', label:active.textContent.trim(), button:a, background:t});
          }
          let scrollableReadouts=0;
          for (const value of document.querySelectorAll('.lp-scale-value')) {
            const card=value.closest('li[data-value]');
            if (!card || !shown(value)) continue;
            const v=rect(value), c=rect(card);
            if (v.left<c.left-1 || v.right>c.right+1) problems.push({kind:'readout-outside-card', text:value.textContent.trim()});
            if (value.scrollWidth>value.clientWidth+1) {
              scrollableReadouts++;
              if (value.tabIndex<0) problems.push({kind:'unreachable-readout', text:value.textContent.trim()});
            }
          }
          return {problems, scrollableReadouts, scrollY, height:document.documentElement.scrollHeight};
        });
        const first=await inspect();
        const anchors=options.anchors || await current.evaluate(maximum => {
          const figures=[...document.querySelectorAll('main figure[id]')];
          const priority=[];
          for (const note of document.querySelectorAll('main .lp-note')) {
            let anchor=document.getElementById((note.getAttribute('data-note-for')||'').replace(/^#/,'')) || note.previousElementSibling;
            while (anchor && (!anchor.getClientRects().length || ['SCRIPT','STYLE','TEMPLATE'].includes(anchor.tagName))) anchor=anchor.previousElementSibling;
            if (anchor && anchor.id) priority.push(anchor.id);
          }
          for (const figure of document.querySelectorAll('.lp-source-tree[id], .lp-timeline[id]')) priority.push(figure.id);
          priority.push(...figures.map(f=>f.id));
          const chosen=new Set([...new Set(priority)].slice(0, maximum));
          return [...document.querySelectorAll('main [id]')].filter(el=>chosen.has(el.id)).map(el=>el.id);
        }, maxLandmarks);
        const positions=() => current.evaluate(ids => Object.fromEntries(ids.map(id=>{
          const el=document.getElementById(id); return [id, el && el.getClientRects().length ? el.getBoundingClientRect().top+scrollY : null];
        })), anchors);
        const baseline=await positions();
        const observations=[];
        for (const id of anchors) {
          const present=await current.evaluate(key => {
            const target=document.getElementById(key); if (!target || !target.getClientRects().length) return false;
            window.scrollTo({top:Math.max(0,target.getBoundingClientRect().top+scrollY-300), behavior:'instant'}); return true;
          }, id);
          if (!present) { issues.push({width,theme,kind:'missing-landmark',anchor:id}); continue; }
          await current.mouse.move(width-16,450);
          await current.mouse.wheel(0,250);
          await current.waitForTimeout(settleMs);
          await current.evaluate(()=>document.dispatchEvent(new CustomEvent('lp:layout')));
          await current.waitForTimeout(160);
          const measured=await inspect(), next=await positions();
          const drift=Object.keys(baseline).filter(key=>baseline[key]!==null && next[key]!==null && Math.abs(next[key]-baseline[key])>32)
            .map(key=>({anchor:key, before:baseline[key], after:next[key]}));
          if (drift.length) measured.problems.push({kind:'scroll-layout-drift', afterAnchor:id, drift});
          observations.push({anchor:id, problems:measured.problems, scrollableReadouts:measured.scrollableReadouts});
          issues.push(...measured.problems.map(problem=>({width,theme,...problem})));
        }
        issues.push(...first.problems.map(problem=>({width,theme,...problem})),...errors.map(message=>({width,theme,kind:'console',message})));
        if (options.screenshotDirectory) {
          await current.evaluate(()=>window.scrollTo({top:0,behavior:'instant'}));
          await current.screenshot({path:options.screenshotDirectory+'/lesson-'+width+'-'+theme+'.png'});
        }
        runs.push({width,theme,normalMotion:true,freshLoad:first.problems.length===0,observations,errors});
      } catch (error) {
        issues.push({width,theme,kind:'check-failed',message:error.message});
      } finally { await context.close(); }
    }
  }
  return {ok:issues.length===0,runs,issues,visualReviewRequired:true};
}
