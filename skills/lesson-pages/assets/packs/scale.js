/* lesson-pages 部件包：对数尺 .lp-scale。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   每个 li 的 data-value 是一个量。卡片按大小排成一排，引线把卡片接到尺上按数量级量出的位置；尺上每个数量级等长，
   中间是 2–9 倍的细刻度。相邻两个量的倍数画成尺下的一段量程：对数尺上同样的倍数同样长。可以切到线性刻度对照，
   看小的量怎样挤到一端、大倍数的那段怎样缩成一点。窄屏时尺竖过来，倍数写在两张卡片之间。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "scale", init: function (ui) {
  var NS = "http://www.w3.org/2000/svg";
  var PREFIX = { "-12": "p", "-9": "n", "-6": "μ", "-3": "m", "0": "", "3": "k", "6": "M", "9": "G", "12": "T", "15": "P", "18": "E" };
  var SUP = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  var num = window.LessonPage.fmt.num;
  function exponent(value) { return Math.floor(Math.log10(value) + 1e-9); }
  function decade(e, unit) {
    var group = Math.floor(e / 3) * 3, prefix = PREFIX[String(group)];
    if (unit && prefix !== undefined) return Math.pow(10, e - group) + " " + prefix + unit;
    return "10" + String(e).replace("-", "⁻").replace(/[0-9]/g, function (d) { return SUP[d]; }) + (unit ? " " + unit : "");
  }
  function si(value, unit) {
    if (!value) return "0";
    var group = Math.floor(exponent(value) / 3) * 3, prefix = PREFIX[String(group)];
    if (!unit || prefix === undefined) return num(value);
    return num(value / Math.pow(10, group)) + " " + prefix + unit;
  }
  function niceStep(max) {
    var raw = max / 4, base = Math.pow(10, exponent(raw)), m = raw / base;
    return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * base;
  }
  function make(tag, cls, parent) {
    var el = document.createElementNS(NS, tag);
    if (cls) el.setAttribute("class", cls);
    parent.appendChild(el);
    return el;
  }
  ui.$all(".lp-scale").forEach(function (figure) {
    try {
      var list = figure.querySelector(":scope > ol");
      if (!list) return;
      var unit = figure.getAttribute("data-unit") || "";
      var items = ui.$all(":scope > li", list).map(function (li) {
        var value = Number(li.getAttribute("data-value"));
        if (!(value > 0) || !isFinite(value)) throw new Error("对数尺上的每个量都要有大于 0 的 data-value");
        return { li: li, value: value };
      }).sort(function (a, b) { return a.value - b.value; });
      if (items.length < 2) return;
      var lo = exponent(items[0].value), hi = Math.ceil(Math.log10(items[items.length - 1].value) - 1e-9);
      if (hi <= lo) hi = lo + 1;
      var vmax = items[items.length - 1].value, step = niceStep(vmax), top = Math.ceil(vmax / step - 1e-9) * step;

      var view = document.createElement("div");
      view.className = "lp-scale-view";
      list.parentNode.insertBefore(view, list);
      view.appendChild(list);
      var chips = items.slice(1).map(function (item, i) {
        var chip = document.createElement("li");
        chip.className = "lp-scale-ratio"; chip.setAttribute("aria-hidden", "true");
        var ratio = item.value / items[i].value;
        chip.textContent = "×" + num(ratio, ratio < 10 ? 1 : 0);
        list.appendChild(chip);
        return chip;
      });
      var svg = make("svg", "lp-scale-lines", view);
      svg.setAttribute("aria-hidden", "true");
      var axis = make("line", "lp-scale-axis", svg), ticks = make("g", "lp-scale-ticks", svg);
      var hops = chips.map(function (chip) {
        var group = make("g", "lp-scale-hop", svg), label;
        make("path", "", group);
        label = make("text", "", group);
        label.textContent = chip.textContent;
        label.setAttribute("text-anchor", "middle");
        return { path: group.firstChild, label: label, width: 0 };
      });
      var leads = items.map(function () { return make("path", "lp-scale-lead", svg); });
      var dots = items.map(function () { return make("circle", "lp-scale-dot", svg); });
      var note = document.createElement("p");
      note.className = "lp-scale-note"; note.hidden = true;
      view.insertAdjacentElement("afterend", note);

      var controls = document.createElement("div");
      controls.className = "lp-scale-mode";
      controls.setAttribute("role", "group"); controls.setAttribute("aria-label", "刻度");
      controls.innerHTML = '<button type="button" aria-pressed="true" data-mode="log">对数刻度</button><button type="button" aria-pressed="false" data-mode="linear">线性刻度</button>';
      view.parentNode.insertBefore(controls, view);

      var mode = "log", shown = null, frame = 0;
      var share = function (value, m) { return m === "log" ? (Math.log10(value) - lo) / (hi - lo) : value / top; };
      var place = function (shares) {
        var vertical = figure.classList.contains("is-vertical");
        var box = view.getBoundingClientRect(), w = view.clientWidth, h = view.clientHeight;
        svg.setAttribute("viewBox", "0 0 " + w + " " + h);
        svg.setAttribute("width", w); svg.setAttribute("height", h);
        var cards = items.map(function (item) {
          var r = item.li.getBoundingClientRect();
          return { left: r.left - box.left, right: r.right - box.left, top: r.top - box.top, bottom: r.bottom - box.top };
        });
        var start, end, at;
        if (vertical) {
          var axisX = 66, first = Math.min.apply(null, cards.map(function (c) { return c.top; })), last = Math.max.apply(null, cards.map(function (c) { return c.bottom; }));
          start = last - 6; end = first + 6;
          at = function (s) { return start + (end - start) * s; };
          axis.setAttribute("x1", axisX); axis.setAttribute("x2", axisX); axis.setAttribute("y1", start + 6); axis.setAttribute("y2", end - 6);
          items.forEach(function (item, i) {
            var y = at(shares[i]), c = cards[i], cy = (c.top + c.bottom) / 2, mid = axisX + 22;
            leads[i].setAttribute("d", "M" + (c.left - 3) + " " + cy + "H" + mid + "V" + y + "H" + (axisX + 6));
            dots[i].setAttribute("cx", axisX); dots[i].setAttribute("cy", y); dots[i].setAttribute("r", 5);
          });
        } else {
          var rowBottom = Math.max.apply(null, cards.map(function (c) { return c.bottom; })), axisY = rowBottom + 54;
          start = 18; end = w - 18;
          at = function (s) { return start + (end - start) * s; };
          axis.setAttribute("x1", start - 6); axis.setAttribute("x2", end + 6); axis.setAttribute("y1", axisY); axis.setAttribute("y2", axisY);
          items.forEach(function (item, i) {
            var x = at(shares[i]), c = cards[i], cx = (c.left + c.right) / 2, mid = rowBottom + 26;
            leads[i].setAttribute("d", "M" + cx + " " + (rowBottom + 3) + "V" + mid + "H" + x + "V" + (axisY - 6));
            dots[i].setAttribute("cx", x); dots[i].setAttribute("cy", axisY); dots[i].setAttribute("r", 5);
          });
          /* 量程：从一个量的位置到下一个量的位置，倍数写在下面；挤在一起时把字往右推开。 */
          var y = axisY + 34, last = -Infinity;
          hops.forEach(function (hop, i) {
            var a = at(shares[i]), b = at(shares[i + 1]);
            hop.path.setAttribute("d", "M" + a + " " + y + "V" + (y + 7) + "H" + b + "V" + y);
            if (!hop.width) hop.width = hop.label.getComputedTextLength();
            var half = (hop.width || 36) / 2, x = Math.min(Math.max((a + b) / 2, last + half + 12, half), w - half);
            hop.label.setAttribute("x", x); hop.label.setAttribute("y", y + 26);
            last = x + half;
          });
        }
        return { vertical: vertical, at: at, start: start, end: end };
      };
      var drawTicks = function (geometry) {
        ticks.textContent = "";
        var marks = [], minor = [];
        if (mode === "log") {
          var every = hi - lo > 8 ? 2 : 1;
          for (var e = lo; e <= hi; e += every) marks.push({ s: (e - lo) / (hi - lo), text: decade(e, unit) });
          /* 每个数量级里 2–9 倍的细刻度，越往上越密：一眼认出这是对数尺。一个数量级太短时不画。 */
          if (Math.abs(geometry.at(1) - geometry.at(0)) / (hi - lo) >= 70) {
            for (e = lo; e < hi; e += 1) for (var k = 2; k < 10; k += 1) minor.push((e + Math.log10(k) - lo) / (hi - lo));
          }
        } else {
          for (var t = 0; t <= top + step / 2; t += step) marks.push({ s: t / top, text: si(t, unit) });
          for (t = step / 5; t < top; t += step / 5) if (Math.abs(t / step - Math.round(t / step)) > 1e-6) minor.push(t / top);
        }
        var y = Number(axis.getAttribute("y1"));
        minor.forEach(function (s) {
          var p = geometry.at(s), tick = make("line", "lp-scale-tick is-minor", ticks);
          if (geometry.vertical) { tick.setAttribute("x1", 63); tick.setAttribute("x2", 69); tick.setAttribute("y1", p); tick.setAttribute("y2", p); }
          else { tick.setAttribute("x1", p); tick.setAttribute("x2", p); tick.setAttribute("y1", y - 3); tick.setAttribute("y2", y + 3); }
        });
        marks.forEach(function (mark) {
          var p = geometry.at(mark.s), tick = make("line", "lp-scale-tick", ticks), label = make("text", "", ticks);
          if (geometry.vertical) {
            tick.setAttribute("x1", 60); tick.setAttribute("x2", 72); tick.setAttribute("y1", p); tick.setAttribute("y2", p);
            label.setAttribute("x", 54); label.setAttribute("y", p + 4); label.setAttribute("text-anchor", "end");
          } else {
            tick.setAttribute("x1", p); tick.setAttribute("x2", p); tick.setAttribute("y1", y - 7); tick.setAttribute("y2", y + 7);
            label.setAttribute("x", p); label.setAttribute("y", y + 24); label.setAttribute("text-anchor", "middle");
          }
          label.textContent = mark.text;
        });
      };
      var layout = function () {
        if (!view.clientWidth || frame) return;
        figure.classList.toggle("is-vertical", figure.clientWidth < 560);
        note.textContent = "线性刻度：最大的量占满整把尺，其余的挤在" + (figure.classList.contains("is-vertical") ? "底端" : "左端") + "几乎分不开，所以跨数量级的量要用对数尺比。";
        items.forEach(function (item, i) {
          var order = figure.classList.contains("is-vertical") ? 2 * (items.length - 1 - i) : 2 * i;
          item.li.style.order = String(order);
          if (chips[i]) chips[i].style.order = String(figure.classList.contains("is-vertical") ? order - 1 : order + 1);
        });
        shown = items.map(function (item) { return share(item.value, mode); });
        hops.forEach(function (hop) { hop.width = 0; });
        drawTicks(place(shown));
      };
      /* 换刻度：引线和圆点在 0.7 秒里滑到新位置，刻度在滑动时隐去、到位后换上；动画期间尺寸变化不打断它。 */
      var animate = function () {
        var from = shown.slice(), to = items.map(function (item) { return share(item.value, mode); }), began = 0;
        figure.setAttribute("data-mode", mode);
        ticks.classList.add("is-swapping");
        window.cancelAnimationFrame(frame);
        var tick = function (time) {
          if (!began) began = time;
          var t = ui.reduceMotion ? 1 : Math.min(1, (time - began) / 700), eased = 1 - Math.pow(1 - t, 3);
          shown = from.map(function (s, i) { return s + (to[i] - s) * eased; });
          var geometry = place(shown);
          if (t < 1) { frame = window.requestAnimationFrame(tick); return; }
          frame = 0;
          drawTicks(geometry);
          ticks.classList.remove("is-swapping");
          note.hidden = mode === "log";
          ui.layout();
        };
        frame = window.requestAnimationFrame(tick);
      };
      controls.addEventListener("click", function (event) {
        var button = event.target.closest("button[data-mode]");
        if (!button || button.getAttribute("data-mode") === mode) return;
        mode = button.getAttribute("data-mode");
        ui.$all("button", controls).forEach(function (b) { b.setAttribute("aria-pressed", b === button ? "true" : "false"); });
        animate();
      });
      items.forEach(function (item, i) {
        var on = function (flag) { item.li.classList.toggle("is-on", flag); dots[i].classList.toggle("is-on", flag); leads[i].classList.toggle("is-on", flag); };
        item.li.addEventListener("mouseenter", function () { on(true); });
        item.li.addEventListener("mouseleave", function () { on(false); });
      });
      figure.classList.add("is-ready");
      figure.setAttribute("data-mode", mode);
      layout();
      if (window.ResizeObserver) new ResizeObserver(function () { layout(); }).observe(figure);
      else window.addEventListener("resize", layout);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(layout);
      /* 打印时 ResizeObserver 不响应，按打印版面的宽度重画一遍尺，印完再按屏幕画回来。 */
      var printing = window.matchMedia && window.matchMedia("print");
      if (printing && printing.addEventListener) printing.addEventListener("change", layout);
      else if (printing && printing.addListener) printing.addListener(layout);
      window.addEventListener("afterprint", layout);
    } catch (error) { ui.failed(figure, error); }
  });
} });
