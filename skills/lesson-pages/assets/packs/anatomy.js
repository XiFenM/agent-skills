/* lesson-pages 部件包：公式解剖 .lp-anatomy。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   公式里用 \tA–\tF 圈出的项，与 ol.lp-terms 的各条说明按顺序对应。宽屏时说明排在公式上下两排，引线连到各项；
   窄屏、打印和没有脚本时，说明是公式下的编号列表，各项头上标同样的编号。指向一项或一条说明，两边一起亮；点按钉住。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "anatomy", init: function (ui) {
  var NS = "http://www.w3.org/2000/svg";
  ui.$all(".lp-anatomy").forEach(function (figure) {
    try {
      var formula = figure.querySelector("div.tex"), list = figure.querySelector("ol.lp-terms");
      if (!formula || !list) return;
      var terms = ui.$all(":scope > li", list).map(function (note, i) {
        var parts = ui.$all(".katex-html .lp-t" + (i + 1), formula);
        if (!parts.length) throw new Error("第 " + (i + 1) + " 条说明在公式里没有对应的 \\t" + "ABCDEF".charAt(i));
        note.setAttribute("tabindex", "0");
        return { n: i + 1, note: note, parts: parts, path: null };
      });
      var stage = document.createElement("div");
      stage.className = "lp-anatomy-stage";
      formula.parentNode.insertBefore(stage, formula);
      stage.appendChild(formula);
      stage.appendChild(list);
      var svg = document.createElementNS(NS, "svg");
      svg.setAttribute("class", "lp-anatomy-lines"); svg.setAttribute("aria-hidden", "true");
      stage.appendChild(svg);
      var pinned = null;
      var light = function (term) {
        figure.classList.toggle("has-on", !!term);
        terms.forEach(function (t) {
          var on = t === term;
          t.note.classList.toggle("is-on", on);
          t.note.classList.toggle("is-pinned", on && t === pinned);
          t.parts.forEach(function (part) { part.classList.toggle("is-on", on); });
          if (t.path) { t.path.classList.toggle("is-on", on); t.badge.classList.toggle("is-on", on); }
        });
      };
      var boxOf = function (t, origin) {
        var left = Infinity, right = -Infinity, top = Infinity, bottom = -Infinity;
        t.parts.forEach(function (part) {
          var r = part.getBoundingClientRect();
          left = Math.min(left, r.left); right = Math.max(right, r.right); top = Math.min(top, r.top); bottom = Math.max(bottom, r.bottom);
        });
        return { left: left - origin.left, right: right - origin.left, top: top - origin.top, bottom: bottom - origin.top };
      };
      var flat = function () {
        figure.classList.remove("is-mapped");
        stage.style.paddingTop = stage.style.paddingBottom = "";
        terms.forEach(function (t) { t.note.style.left = t.note.style.top = ""; t.path = null; });
        svg.textContent = "";
      };
      /* 先把说明排成上下两排，排得下才画引线；一排挤不下（比如六项都长）就退回编号列表。 */
      var place = function () {
        flat();
        var width = stage.clientWidth;
        if (width < 520 || formula.scrollWidth > formula.clientWidth + 1) return;
        /* 宽屏时公式放大成图的主角；放大后排不下就仍用列表。 */
        figure.classList.add("is-mapped");
        if (formula.scrollWidth > formula.clientWidth + 1) { flat(); return; }
        var sizes = terms.map(function (t) { return { w: t.note.offsetWidth, h: t.note.offsetHeight }; });
        var origin = stage.getBoundingClientRect();
        var centers = terms.map(function (t) { var b = boxOf(t, origin); return (b.left + b.right) / 2; });
        var order = terms.map(function (t, i) { return i; }).sort(function (a, b) { return centers[a] - centers[b]; });
        var rows = [[], []];
        order.forEach(function (i, k) { rows[terms.length < 2 ? 0 : k % 2].push(i); });
        var fits = true;
        var lefts = rows.map(function (row) {
          var at = row.map(function (i) { return centers[i] - sizes[i].w / 2; }), k;
          for (k = 1; k < row.length; k += 1) at[k] = Math.max(at[k], at[k - 1] + sizes[row[k - 1]].w + 14);
          for (k = row.length - 1; k >= 0; k -= 1) at[k] = Math.min(at[k], (k < row.length - 1 ? at[k + 1] - 14 : width) - sizes[row[k]].w);
          for (k = 0; k < row.length; k += 1) {
            if (at[k] < 0 || (k && at[k] < at[k - 1] + sizes[row[k - 1]].w + 8)) fits = false;
          }
          return at;
        });
        if (!fits) { flat(); return; }
        var gap = 38;
        var rowH = rows.map(function (row) { return row.reduce(function (m, i) { return Math.max(m, sizes[i].h); }, 0); });
        stage.style.paddingTop = (rowH[0] ? rowH[0] + gap : 0) + "px";
        stage.style.paddingBottom = (rowH[1] ? rowH[1] + gap : 0) + "px";
        origin = stage.getBoundingClientRect();
        var boxes = terms.map(function (t) { return boxOf(t, origin); });
        var height = (rowH[0] ? rowH[0] + gap : 0) + formula.offsetHeight + (rowH[1] ? rowH[1] + gap : 0);
        svg.setAttribute("viewBox", "0 0 " + width + " " + height);
        svg.setAttribute("width", width); svg.setAttribute("height", height);
        rows.forEach(function (row, r) {
          row.forEach(function (i, k) {
            var t = terms[i], b = boxes[i], s = sizes[i], left = lefts[r][k];
            var top = r === 0 ? rowH[0] - s.h : height - rowH[1];
            t.note.style.left = left + "px";
            t.note.style.top = top + "px";
            var cx = (b.left + b.right) / 2, anchor = Math.max(left + 14, Math.min(left + s.w - 14, cx));
            var edge = r === 0 ? b.top - 8 : b.bottom + 10, tick = r === 0 ? 5 : -5;
            var end = r === 0 ? top + s.h + 1 : top - 1, mid = Math.round((edge + end) / 2);
            var path = document.createElementNS(NS, "path");
            path.setAttribute("class", "lp-anatomy-line");
            path.setAttribute("pathLength", "1");
            path.setAttribute("d", "M" + (b.left + 1) + " " + (edge + tick) + "V" + edge + "H" + (b.right - 1) + "V" + (edge + tick) +
              "M" + cx + " " + edge + "V" + mid + "H" + anchor + "V" + end);
            svg.appendChild(path);
            t.path = path;
            /* 括号正中挂一个同号的圆牌：公式这边也看得出是第几项。 */
            var badge = document.createElementNS(NS, "g"), disc = document.createElementNS(NS, "circle"), digit = document.createElementNS(NS, "text");
            badge.setAttribute("class", "lp-anatomy-num");
            badge.setAttribute("transform", "translate(" + cx + " " + edge + ")");
            disc.setAttribute("r", "8.5");
            digit.setAttribute("y", "3.6"); digit.setAttribute("text-anchor", "middle");
            digit.textContent = String(t.n);
            badge.appendChild(disc); badge.appendChild(digit);
            svg.appendChild(badge);
            t.badge = badge;
          });
        });
      };
      /* 隐藏时（只看要点）不动版面；量的过程中按原高度占位，页面不会先缩一下再弹回去。 */
      var laidWidth = -1;
      var layout = function (force) {
        var width = stage.clientWidth;
        if (!width || (!force && width === laidWidth)) return;
        laidWidth = width;
        stage.style.minHeight = stage.offsetHeight + "px";
        try { place(); } finally { stage.style.minHeight = ""; }
        light(pinned);
      };
      terms.forEach(function (t) {
        var enter = function () { if (!pinned) light(t); }, leave = function () { light(pinned); };
        var pin = function () { pinned = pinned === t ? null : t; light(pinned || t); };
        [t.note].concat(t.parts).forEach(function (el) {
          el.addEventListener("mouseenter", enter);
          el.addEventListener("mouseleave", leave);
          el.addEventListener("click", pin);
        });
        t.note.addEventListener("focus", function () { light(t); });
        t.note.addEventListener("blur", function () { light(pinned); });
        t.note.addEventListener("keydown", function (event) { if (event.key === "Enter" || event.key === " ") { pin(); event.preventDefault(); } });
      });
      figure.classList.add("is-ready");
      layout(true);
      var later = 0, again = function () { window.clearTimeout(later); later = window.setTimeout(function () { layout(false); }, 60); };
      if (window.ResizeObserver) new ResizeObserver(again).observe(figure);
      window.addEventListener("resize", again);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { layout(true); });
      window.addEventListener("beforeprint", function () { flat(); laidWidth = -1; });
      window.addEventListener("afterprint", function () { layout(true); });
    } catch (error) { ui.failed(figure, error); }
  });
} });
