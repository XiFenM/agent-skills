/* lesson-pages 部件包：执行回放 .lp-replay。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   图里一段 pre.lp-code 和一张 ol.lp-trace 轨迹：每个 li 是一步，data-line 是执行到的行，data-set 是这一步改变的变量
  （名字=值，空格分开），data-group 从这一步开始一段（如“第 2 块”），data-call 是函数又一次被调用（变量表从空开始），li 的文字是这一步的说明。轨迹要来自真实运行。
   有脚本时：当前行亮起、变量表跟着变（改了的变量闪一下，带旧值和走势），底下一条可拖动的时间轴按段分色。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "replay", init: function (ui) {
  var NS = "http://www.w3.org/2000/svg";
  /* 形如 [4.5,0.8,2.2,1] 的值是一列数：画成一排小格，格底的柱高是这个数占本列最大绝对值的比例。 */
  var listOf = function (raw) {
    var m = String(raw == null ? "" : raw).trim().match(/^\[(.*)\]$/);
    if (!m) return null;
    var parts = m[1].split(",").map(function (x) { return x.trim(); });
    return parts.length && parts.every(function (x) { return x !== "" && isFinite(Number(x.replace(/−/g, "-"))); }) ? parts : null;
  };
  /* data-set 只按 ASCII 空白分开：trace 把值里的空白写成不换行空格，它属于值本身。 */
  var GAP = /[ \t\n\r\f]+/;
  var number = function (raw) {
    var text = String(raw == null ? "" : raw).trim().replace(/−/g, "-");
    if (text === "∞" || text === "+∞" || text === "inf") return Infinity;
    if (text === "-∞" || text === "-inf") return -Infinity;
    var n = Number(text);
    return text !== "" && isFinite(n) ? n : null;
  };
  ui.$all(".lp-replay").forEach(function (figure) {
    try {
      var pre = figure.querySelector("pre.lp-code"), trace = figure.querySelector("ol.lp-trace");
      if (!pre || !trace) return;
      figure.classList.add("is-stage");
      var steps = ui.$all(":scope > li", trace).map(function (li) {
        var set = {}, keys = [];
        String(li.getAttribute("data-set") || "").split(GAP).filter(Boolean).forEach(function (pair) {
          var at = pair.indexOf("=");
          if (at < 1) throw new Error("轨迹的 data-set 要写成 名字=值，用空格分开：" + pair);
          set[pair.slice(0, at)] = pair.slice(at + 1);
          keys.push(pair.slice(0, at));
        });
        return { line: li.getAttribute("data-line"), set: set, keys: keys, group: li.getAttribute("data-group"), call: li.hasAttribute("data-call"), say: li.innerHTML };
      });
      if (steps.length < 2) return;
      var names = String(trace.getAttribute("data-vars") || "").split(/\s+/).filter(Boolean);
      steps.forEach(function (s) { s.keys.forEach(function (k) { if (names.indexOf(k) < 0) names.push(k); }); });
      var states = [], now = {};
      steps.forEach(function (s) { now = Object.assign({}, s.call ? {} : now, s.set); states.push(now); });
      var colors = {};
      String(pre.getAttribute("data-symbols") || "").split(/\s+/).forEach(function (pair) {
        var m = pair.match(/^([A-Za-z_][A-Za-z0-9_]*)=([1-4])$/);
        if (m) colors[m[1]] = m[2];
      });
      var lines = {};
      ui.$all(".lp-line", pre).forEach(function (line) { lines[line.getAttribute("data-n")] = line; });
      steps.forEach(function (s, i) { if (!lines[s.line]) throw new Error("轨迹第 " + (i + 1) + " 步的 data-line=" + s.line + " 不在代码里"); });

      /* 版面：代码与变量表并排，说明在变量表下，时间轴在最底下。 */
      var head = pre.previousElementSibling && pre.previousElementSibling.classList.contains("lp-code-head") ? pre.previousElementSibling : null;
      var mainBox = document.createElement("div"), codeBox = document.createElement("div"), side = document.createElement("div");
      mainBox.className = "lp-replay-main"; codeBox.className = "lp-replay-code"; side.className = "lp-replay-side";
      pre.parentNode.insertBefore(mainBox, head || pre);
      if (head) codeBox.appendChild(head);
      codeBox.appendChild(pre);
      mainBox.appendChild(codeBox); mainBox.appendChild(side);
      var table = document.createElement("dl");
      table.className = "lp-replay-vars";
      side.appendChild(table);
      var say = document.createElement("p");
      say.className = "lp-replay-say"; say.setAttribute("aria-live", "polite");
      side.appendChild(say);
      var cells = names.map(function (name) {
        var row = document.createElement("div"), term = document.createElement("dt"), value = document.createElement("dd");
        row.setAttribute("data-var", name);
        var label = document.createElement("span");
        label.textContent = name;
        if (colors[name]) label.className = "lp-s" + colors[name];
        term.appendChild(label);
        value.innerHTML = "<b></b><small></small>";
        row.appendChild(term); row.appendChild(value);
        var series = states.map(function (st) { return number(st[name]); });
        var finite = series.filter(function (v) { return v !== null && isFinite(v); });
        var spark = null;
        if (finite.length >= 3 && Math.max.apply(null, finite) > Math.min.apply(null, finite)) {
          spark = document.createElementNS(NS, "svg");
          spark.setAttribute("class", "lp-replay-spark");
          spark.setAttribute("viewBox", "0 0 72 24"); spark.setAttribute("aria-hidden", "true");
          /* 符号色写在走势线自己身上（不写在 svg 上），指向这个符号时走势线随之发光。 */
          var tone = colors[name] ? ' class="lp-s' + colors[name] + '"' : "";
          spark.innerHTML = '<path class="lp-spark-all"/><g' + tone + '><path class="lp-spark-past"/><circle r="2.6"/></g>';
          row.appendChild(spark);
          row.classList.add("has-spark");
        }
        if (states.some(function (st) { return listOf(st[name]); })) row.classList.add("is-list");
        table.appendChild(row);
        var lo = Math.min.apply(null, finite), hi = Math.max.apply(null, finite);
        var pt = function (i) { var v = series[i]; return (2 + 68 * i / (steps.length - 1)).toFixed(1) + " " + (21 - 18 * (v - lo) / ((hi - lo) || 1)).toFixed(1); };
        var trail = function (upto) {
          var d = "", pen = false;
          for (var i = 0; i <= upto; i += 1) {
            if (series[i] === null || !isFinite(series[i])) { pen = false; continue; }
            d += (pen ? "L" : "M") + pt(i); pen = true;
          }
          return d;
        };
        if (spark) spark.querySelector(".lp-spark-all").setAttribute("d", trail(steps.length - 1));
        return { row: row, value: value.firstChild, before: value.lastChild, spark: spark, trail: trail, pt: pt, series: series };
      });

      var bar = document.createElement("div");
      bar.className = "lp-replay-bar";
      bar.innerHTML = '<button type="button" class="lp-btn" data-act="prev" aria-label="上一步">‹</button>' +
        '<button type="button" class="lp-btn is-primary" data-act="play" aria-pressed="false">播放</button>' +
        '<button type="button" class="lp-btn" data-act="next" aria-label="下一步">›</button>' +
        '<div class="lp-replay-track"><div class="lp-replay-groups" aria-hidden="true"></div><input type="range" min="0" step="1" aria-label="执行到第几步"></div>' +
        '<span class="lp-replay-count"></span>';
      mainBox.insertAdjacentElement("afterend", bar);
      var range = bar.querySelector("input"), count = bar.querySelector(".lp-replay-count"), play = bar.querySelector('[data-act="play"]');
      range.max = String(steps.length - 1);
      var groups = bar.querySelector(".lp-replay-groups"), bands = [];
      steps.forEach(function (s, i) { if (s.group || i === 0) bands.push({ start: i, label: s.group || "" }); });
      bands.forEach(function (band, k) {
        var end = k + 1 < bands.length ? bands[k + 1].start : steps.length;
        var span = document.createElement("span");
        span.style.left = (100 * band.start / steps.length) + "%";
        span.style.width = (100 * (end - band.start) / steps.length) + "%";
        span.textContent = band.label;
        span.title = band.label;
        groups.appendChild(span);
        band.el = span;
      });
      /* 段太窄放不下名字时只留分隔线，名字在悬停提示里。 */
      var fit = function () { bands.forEach(function (band) { band.el.classList.toggle("is-tight", band.el.scrollWidth > band.el.clientWidth + 1); }); };
      if (window.ResizeObserver) new ResizeObserver(fit).observe(groups);

      var index = 0, timer = 0, measuring = false;
      var prev = bar.querySelector('[data-act="prev"]'), next = bar.querySelector('[data-act="next"]');
      var render = function () {
        var step = steps[index], prior = index ? steps[index - 1] : null;
        Object.keys(lines).forEach(function (n) { lines[n].classList.remove("is-run", "is-ran"); });
        if (prior && prior.line !== step.line) lines[prior.line].classList.add("is-ran");
        lines[step.line].classList.add("is-run");
        cells.forEach(function (cell, k) {
          var name = names[k], value = states[index][name], old = index && !step.call ? states[index - 1][name] : undefined;
          var list = listOf(value), changed = step.keys.indexOf(name) >= 0;
          if (list) {
            var top = Math.max.apply(null, list.map(function (x) { return Math.abs(Number(x.replace(/−/g, "-"))); })) || 1;
            cell.value.innerHTML = '<span class="lp-replay-list">' + list.map(function (x) {
              return '<i style="--h:' + (Math.abs(Number(x.replace(/−/g, "-"))) / top).toFixed(3) + '">' + x.replace(/-/g, "−") + "</i>";
            }).join("") + "</span>";
          } else cell.value.textContent = value === undefined ? "—" : value;
          cell.before.textContent = changed && old !== undefined && old !== value ? (list ? "原来 " + old : old + " → " + value) : changed ? "新值" : "";
          cell.row.classList.remove("is-changed");
          if (changed && !measuring) { void cell.row.offsetWidth; cell.row.classList.add("is-changed"); }
          cell.row.classList.toggle("is-unset", value === undefined);
          if (cell.spark) {
            cell.spark.querySelector(".lp-spark-past").setAttribute("d", cell.trail(index));
            var dot = cell.spark.querySelector("circle"), v = cell.series[index];
            dot.style.display = v === null || !isFinite(v) ? "none" : "";
            if (v !== null && isFinite(v)) { var p = cell.pt(index).split(" "); dot.setAttribute("cx", p[0]); dot.setAttribute("cy", p[1]); }
          }
        });
        say.innerHTML = '<span class="lp-replay-now"><span class="lp-replay-at">第 ' + step.line + " 行</span>" + step.say + "</span>";
        ui.decorate(say);
        range.value = String(index);
        range.setAttribute("aria-valuetext", "第 " + (index + 1) + " 步，共 " + steps.length + " 步，执行第 " + step.line + " 行");
        range.style.setProperty("--p", (100 * index / (steps.length - 1)).toFixed(2) + "%");
        count.textContent = (index + 1) + " / " + steps.length;
        bands.forEach(function (band, k) {
          var end = k + 1 < bands.length ? bands[k + 1].start : steps.length;
          band.el.classList.toggle("is-now", index >= band.start && index < end);
        });
        /* 按到头的那个按钮会被停用；焦点正在它上面时交给另一个，键盘操作不断线。 */
        var focused = document.activeElement;
        prev.disabled = index === 0;
        next.disabled = index === steps.length - 1;
        if (!measuring && ((focused === prev && prev.disabled) || (focused === next && next.disabled))) (prev.disabled ? next : prev).focus({ preventScroll: true });
        if (!timer) play.textContent = index === steps.length - 1 ? "重播" : "播放";
        figure.setAttribute("data-step", String(index + 1));
      };
      var stop = function () {
        window.clearInterval(timer); timer = 0;
        play.setAttribute("aria-pressed", "false");
        play.textContent = index === steps.length - 1 ? "重播" : "播放";
      };
      var go = function (to) { index = Math.max(0, Math.min(steps.length - 1, to)); render(); };
      bar.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-act]");
        if (!button) return;
        var act = button.getAttribute("data-act");
        if (act === "play") {
          if (timer) { stop(); return; }
          if (index === steps.length - 1) go(0);
          play.textContent = "暂停"; play.setAttribute("aria-pressed", "true");
          timer = window.setInterval(function () {
            if (index >= steps.length - 1) { stop(); return; }
            go(index + 1);
            if (index >= steps.length - 1) stop();
          }, ui.reduceMotion ? 1600 : 1100);
          return;
        }
        stop();
        go(index + (act === "next" ? 1 : -1));
      });
      range.addEventListener("input", function () { stop(); go(parseInt(range.value, 10)); });
      figure.addEventListener("keydown", function (event) {
        if (event.altKey || event.ctrlKey || event.metaKey || event.target === range) return;
        if (event.target.closest && event.target.closest("pre.lp-code")) return;
        var delta = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
        if (delta) { stop(); go(index + delta); event.preventDefault(); }
        else if (event.key === "Home" || event.key === "End") { stop(); go(event.key === "Home" ? 0 : steps.length - 1); event.preventDefault(); }
      });
      if (!figure.hasAttribute("tabindex")) figure.setAttribute("tabindex", "-1");
      /* 代码横向放不下时要能用键盘滚动：这时代码块本身可以聚焦，是一个有名字的区域 */
      var own = !pre.hasAttribute("tabindex");
      var scrollable = function () {
        if (!own) return;
        if (pre.scrollWidth > pre.clientWidth + 1) {
          pre.setAttribute("tabindex", "0"); pre.setAttribute("role", "region");
          pre.setAttribute("aria-label", "代码" + (pre.getAttribute("data-title") ? " " + pre.getAttribute("data-title") : ""));
        } else ["tabindex", "role", "aria-label"].forEach(function (name) { pre.removeAttribute(name); });
      };
      figure.classList.add("is-ready");
      /* 版面按图自己的宽度切换：窄时变量表排到代码下面。变量表和说明先按所有步里最高的那一步占好高度，
         翻步时下面的按钮不会上下跳。 */
      var width = -1;
      var reserve = function () {
        var w = figure.clientWidth;
        if (!w || w === width) return;
        width = w;
        figure.classList.toggle("is-narrow", w < 760);
        side.style.minHeight = "";
        var keep = index, tallest = 0;
        measuring = true;
        for (index = 0; index < steps.length; index += 1) { render(); tallest = Math.max(tallest, side.offsetHeight); }
        measuring = false;
        index = keep;
        side.style.minHeight = tallest + "px";
        render();
        scrollable();
      };
      render();
      reserve();
      if (window.ResizeObserver) new ResizeObserver(reserve).observe(figure);
      else window.addEventListener("resize", reserve);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () { width = -1; reserve(); });
    } catch (error) { ui.failed(figure, error); }
  });
} });
