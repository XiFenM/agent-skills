/* lesson-pages 部件包：海报式开场 .lp-poster。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   一两个超大数字，第一次出现时从 0 数到写下的值，只数一次。两个数字的单位能换算时（MiB 与 KB、ms 与 s、同名单位），
   中间按倍数写“≫ > = < ≪”，并在下面铺一片格子：整片是大的量，亮起的一格是小的量，倍数一眼看得见；
   单位换算不了时中间写“≫”，不画格子。格子只是写下的两个量的图示，屏幕阅读器始终读到写下的值。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "poster", init: function (ui) {
  var BYTE = { "": 0, k: 1, K: 1, M: 2, G: 3, T: 4, P: 5, E: 6 };
  var SI = { n: -9, "μ": -6, u: -6, m: -3, k: 3, K: 3, M: 6, G: 9, T: 12, P: 15 };
  /* 一个量的几种读法：字节类单位按 1024 进位换算成 B（可带 /s）；其余单位原样一种，去掉一个 SI 前缀再一种。 */
  var readings = function (value, unit) {
    var bytes = unit.match(/^([kKMGTPE]?)i?B(\/s)?$/);
    if (bytes) return [{ base: "B" + (bytes[2] || ""), value: value * Math.pow(1024, BYTE[bytes[1]]) }];
    var list = [{ base: unit, value: value }];
    if (unit.length > 1 && SI[unit.charAt(0)] !== undefined) list.push({ base: unit.slice(1), value: value * Math.pow(10, SI[unit.charAt(0)]) });
    return list;
  };
  var ratioOf = function (a, b) {
    var found = null;
    readings(a.value, a.unit).forEach(function (x) {
      readings(b.value, b.unit).forEach(function (y) { if (found === null && x.base === y.base && x.value > 0 && y.value > 0) found = x.value / y.value; });
    });
    return found;
  };
  ui.$all(".lp-poster").forEach(function (poster) {
    try {
      var nums = ui.$all(":scope > .lp-poster-num", poster);
      var info = nums.map(function (num) {
        var digits = num.querySelector("b"), unit = num.querySelector("small"), text = digits ? digits.textContent.trim() : "";
        var match = text.match(/^([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.([0-9]+))?$/);
        return { num: num, digits: digits, text: text, match: match, value: Number(text.replace(/,/g, "")),
          unit: unit ? unit.textContent.replace(/\s+/g, "").replace(/\u00b5/g, "\u03bc") : "", label: text + (unit ? " " + unit.textContent.trim() : "") };
      });
      var field = null, setFill = function () {};
      if (nums.length === 2) {
        var ratio = info[0].match && info[1].match ? ratioOf(info[0], info[1]) : null;
        var vs = document.createElement("span");
        vs.className = "lp-poster-vs"; vs.setAttribute("aria-hidden", "true");
        vs.textContent = ratio === null || ratio >= 10 ? "≫" : ratio > 1 ? ">" : ratio === 1 ? "=" : ratio > 0.1 ? "<" : "≪";
        poster.insertBefore(vs, nums[1]);
        poster.classList.add("is-pair");
        var times = ratio === null ? 0 : Math.max(ratio, 1 / ratio);
        if (times >= 10 && times <= 20000) {
          var big = ratio >= 1 ? info[0] : info[1], small = ratio >= 1 ? info[1] : info[0], count = Math.round(times);
          small.num.classList.add("is-small");
          poster.classList.add("has-field");
          field = document.createElement("div");
          field.className = "lp-poster-field"; field.setAttribute("aria-hidden", "true");
          field.innerHTML = '<div class="lp-poster-key"><span></span><span></span></div>' +
            '<div class="lp-poster-grid"><i class="lp-poster-rows"></i><i class="lp-poster-rest"></i><i class="lp-poster-one"></i></div>';
          var keys = field.querySelectorAll(".lp-poster-key span");
          keys[0].textContent = "一格 = " + small.label;
          keys[1].textContent = "整片 = " + big.label;
          poster.insertBefore(field, poster.querySelector(":scope > .lp-poster-say"));
          /* 格子的边长按可用宽度定：整片高度大致固定，格子数恰好等于倍数（四舍五入），最后一行可以不满。 */
          /* 宽度量整张海报：格子太密时整片藏起，藏起后它自己的宽度是 0，量它就再也回不来。 */
          var lay = function () {
            var width = poster.clientWidth;
            if (!width) return;
            var pitch = Math.max(3, Math.min(30, Math.floor(Math.sqrt(width * (width < 480 ? 150 : 128) / count))));
            var cols = Math.max(1, Math.min(count, Math.floor(width / pitch))), rows = Math.floor(count / cols);
            field.style.setProperty("--pitch", pitch + "px");
            field.style.setProperty("--cols", String(cols));
            field.style.setProperty("--rows", String(rows));
            field.style.setProperty("--rest", String(count - rows * cols));
            field.classList.toggle("is-too-dense", (rows + 1) * pitch > 300);
          };
          lay();
          if (window.ResizeObserver) new ResizeObserver(lay).observe(poster);
          else window.addEventListener("resize", lay);
          setFill = function (v) { field.style.setProperty("--fill", String(v)); };
        }
      }
      var counters = info.map(function (c) {
        if (!c.match) return null;
        var places = c.match[2] ? c.match[2].length : 0, grouped = c.text.indexOf(",") >= 0, digits = c.digits;
        var spoken = document.createElement("span");
        spoken.className = "lp-visually-hidden"; spoken.textContent = c.text;
        digits.parentNode.insertBefore(spoken, digits);
        digits.setAttribute("aria-hidden", "true");
        return {
          el: digits, text: c.text, target: c.value,
          show: function (v) { digits.textContent = grouped ? v.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places }) : v.toFixed(places); }
        };
      }).filter(Boolean);
      if (ui.reduceMotion || !counters.length || !("IntersectionObserver" in window)) return;
      /* 数的过程中按写下的值占住宽度，字不跳；数完放开，打印或换字号时按实际宽度排。 */
      counters.forEach(function (c) { c.el.style.minWidth = c.el.getBoundingClientRect().width + "px"; c.show(0); });
      setFill(0);
      poster.classList.add("is-waiting");
      var done = false;
      var finish = function () {
        done = true;
        counters.forEach(function (c) { c.el.textContent = c.text; c.el.style.minWidth = ""; });
        setFill(1);
        poster.classList.remove("is-waiting", "is-counting");
        poster.classList.add("is-counted");
      };
      window.addEventListener("beforeprint", finish);
      ui.inView(poster, function () {
        if (done) return;
        poster.classList.remove("is-waiting");
        poster.classList.add("is-counting");
        var began = 0;
        var tick = function (time) {
          if (done) return;
          if (!began) began = time;
          var t = Math.min(1, (time - began) / 1300), eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
          counters.forEach(function (c, i) {
            var lag = Math.max(0, Math.min(1, (t - i * 0.12) / (1 - i * 0.12))), e = lag === 1 ? 1 : 1 - Math.pow(2, -10 * lag);
            c.show(c.target * (counters.length > 1 ? e : eased));
          });
          setFill(eased);
          if (t < 1) window.requestAnimationFrame(tick);
          else finish();
        };
        window.requestAnimationFrame(tick);
      }, "0px 0px -10% 0px");
    } catch (error) { ui.failed(poster, error); }
  });
} });
