/* lesson-pages 部件包：逐行推导 .lp-derive。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   ol 的每个 li 是一步：一个行间公式加一句理由，每步变化的部分用 \hl 标出。先只给第一步（后面的步留着位置），按“下一步”逐行展开，
   新出现的一行里标出的变化闪一下；以“=”开头的续行，等号对齐到第一行的等号。没有脚本、打印时全部显示。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "derive", init: function (ui) {
  ui.$all(".lp-derive").forEach(function (figure) {
    try {
      var list = figure.querySelector(":scope > ol"), steps = list ? ui.$all(":scope > li", list) : [];
      if (steps.length < 2) return;
      var shown = 1;
      var controls = document.createElement("div");
      controls.className = "lp-controls lp-derive-controls";
      controls.innerHTML = '<button type="button" class="lp-btn is-primary" data-act="next">下一步</button><button type="button" class="lp-btn is-quiet" data-act="all">全部展开</button><span class="lp-derive-count"></span>';
      list.insertAdjacentElement("afterend", controls);
      list.setAttribute("aria-live", "polite");
      var next = controls.querySelector('[data-act="next"]'), all = controls.querySelector('[data-act="all"]'), count = controls.querySelector(".lp-derive-count");
      var relOf = function (step) {
        var html = step.querySelector(".katex-display .katex-html");
        return html ? html.querySelector(".mrel") : null;
      };
      /* 续行的第一个符号是关系符时，把它挪到第一行关系符的正下方。 */
      var align = function () {
        var anchor = relOf(steps[0]);
        steps.forEach(function (step) { var tex = step.querySelector("div.tex"); if (tex) tex.style.paddingLeft = ""; });
        if (!anchor || !anchor.getClientRects().length) return;
        var x = anchor.getBoundingClientRect().left;
        steps.slice(1).forEach(function (step) {
          var tex = step.querySelector("div.tex"), rel = relOf(step);
          if (!tex || !rel || !rel.getClientRects().length || tex.scrollWidth > tex.clientWidth + 1) return;
          var html = step.querySelector(".katex-html"), first = html.getBoundingClientRect().left;
          if (rel.getBoundingClientRect().left - first > 2) return;
          var shift = x - rel.getBoundingClientRect().left;
          if (shift > 0) tex.style.paddingLeft = (shift + (parseFloat(window.getComputedStyle(tex).paddingLeft) || 0)) + "px";
          if (tex.scrollWidth > tex.clientWidth + 1) tex.style.paddingLeft = "";
        });
      };
      var render = function (fresh) {
        steps.forEach(function (step, i) {
          step.classList.toggle("is-hidden", i >= shown);
          step.classList.remove("is-fresh");
          if (fresh && i === shown - 1) { void step.offsetWidth; step.classList.add("is-fresh"); }
        });
        var done = shown >= steps.length;
        figure.classList.toggle("is-done", done);
        count.textContent = shown + " / " + steps.length;
        next.textContent = done ? "从头再看" : "下一步";
        next.classList.toggle("is-primary", !done);
        /* “全部展开”收起时焦点正在它上面，就交给旁边的按钮，键盘不会掉回页首。 */
        if (done && document.activeElement === all) next.focus({ preventScroll: true });
        all.hidden = done;
        align();
      };
      controls.addEventListener("click", function (event) {
        var button = event.target.closest("button");
        if (!button) return;
        if (button === all) { shown = steps.length; render(false); }
        else if (shown >= steps.length) { shown = 1; render(false); }
        else { shown += 1; render(true); }
        ui.layout();
      });
      figure.classList.add("is-ready");
      render(false);
      var later = 0;
      window.addEventListener("resize", function () { window.clearTimeout(later); later = window.setTimeout(align, 80); });
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(align);
    } catch (error) { ui.failed(figure, error); }
  });
} });
