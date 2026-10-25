/* lesson-pages 部件包：可缩放的系统结构图 .lp-zoom。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   嵌套列表写系统的层次：最外层恰好一个 li 是整个系统；每个 li 里 <b> 是部件名，<p> 是说明，ul 是它的下一层，
   data-size（1–3）是它在这一层里占的分量。有脚本时画成一张能逐层放大的图：点带下一层的部件，它铺满画面、露出下一层。
   放大后外面几层还在：画面一圈套一圈，每圈顶上写着那一层的名字，点名字退回那一层（“上一层”和 Esc 也退回）。
   带下一层的部件里画着下一层的缩略图。figure 的 data-domain（hardware、software）决定底纹和部件的样子。
   没有脚本、打印时是缩进的提纲。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "zoom", init: function (ui) {
  var nodeOf = function (li) {
    var title = li.querySelector(":scope > b"), text = li.querySelector(":scope > p"), sub = li.querySelector(":scope > ul");
    return {
      title: title ? title.innerHTML : "", plain: title ? ui.plainText(title) : "",
      text: text ? text.innerHTML : "",
      size: Math.max(1, Math.min(3, parseInt(li.getAttribute("data-size") || "1", 10) || 1)),
      kids: sub ? ui.$all(":scope > li", sub).map(nodeOf) : []
    };
  };
  ui.$all(".lp-zoom").forEach(function (figure) {
    try {
      var outline = figure.querySelector(":scope > ul"), tops = outline ? ui.$all(":scope > li", outline) : [];
      if (tops.length !== 1) throw new Error("系统结构图的最外层要恰好一个 li，代表整个系统");
      var system = nodeOf(tops[0]);
      figure.classList.add("is-stage");
      var view = document.createElement("div");
      view.className = "lp-zoom-view";
      view.innerHTML = '<div class="lp-zoom-bar"><p class="lp-zoom-hint"></p>' +
        '<button type="button" class="lp-btn lp-zoom-up">↑ 上一层</button></div>' +
        '<div class="lp-zoom-frame"><nav class="lp-zoom-path" aria-label="外面的几层"></nav><i class="lp-zoom-here" aria-hidden="true"></i>' +
        '<div class="lp-zoom-head"><p class="lp-zoom-title" tabindex="-1"></p><p class="lp-zoom-about"></p></div>' +
        '<div class="lp-zoom-kids"></div></div>';
      outline.parentNode.insertBefore(view, outline);
      var frame = view.querySelector(".lp-zoom-frame"), kidsBox = view.querySelector(".lp-zoom-kids"), rings = view.querySelector(".lp-zoom-path");
      var here = view.querySelector(".lp-zoom-here"), hint = view.querySelector(".lp-zoom-hint");
      var up = view.querySelector(".lp-zoom-up"), title = view.querySelector(".lp-zoom-title"), about = view.querySelector(".lp-zoom-about");
      var trail = [system], busy = false, queued = 0;
      var draw = function () {
        var node = trail[trail.length - 1], depth = trail.length;
        title.innerHTML = node.title;
        about.innerHTML = node.text;
        about.hidden = !node.text;
        hint.textContent = depth > 1 ? "点外圈的名字或“上一层”退回" : node.kids.some(function (kid) { return kid.kids.length; }) ? "点带“放大”的部件，进入下一层" : "";
        /* 外面的每一层是一圈，名字写在这一圈的顶边上。 */
        rings.textContent = "";
        trail.slice(0, -1).forEach(function (step, k) {
          var ring = document.createElement("div"), name = document.createElement("button");
          ring.className = "lp-zoom-ring"; ring.style.setProperty("--k", String(k));
          name.type = "button"; name.innerHTML = step.title;
          name.addEventListener("click", function () { back(k + 1); });
          ring.appendChild(name);
          rings.appendChild(ring);
        });
        rings.hidden = depth === 1;
        frame.style.setProperty("--rings", String(depth - 1));
        up.disabled = depth === 1;
        kidsBox.textContent = "";
        node.kids.forEach(function (kid) {
          var deep = kid.kids.length > 0, box = document.createElement(deep ? "button" : "div");
          box.className = "lp-zoom-box" + (deep ? " can-zoom" : "");
          if (deep) box.type = "button";
          if (kid.size > 1) box.setAttribute("data-size", String(kid.size));
          var row = document.createElement("span"), name = document.createElement("b"), text = document.createElement("span");
          row.className = "lp-zoom-row"; text.className = "lp-zoom-text";
          name.innerHTML = kid.title; text.innerHTML = kid.text;
          row.appendChild(name);
          box.appendChild(row);
          if (kid.text) box.appendChild(text);
          if (deep) {
            /* 缩略图：下一层的部件按各自的分量排成小格，放大后就是这些格子。 */
            var mini = document.createElement("span"), go = document.createElement("em");
            mini.className = "lp-zoom-mini"; mini.setAttribute("aria-hidden", "true");
            kid.kids.slice(0, 8).forEach(function (grand) {
              var cell = document.createElement("i");
              cell.textContent = grand.plain;
              if (grand.size > 1) cell.setAttribute("data-size", String(grand.size));
              if (grand.kids.length) cell.className = "is-deep";
              mini.appendChild(cell);
            });
            if (kid.kids.length > 8) { var more = document.createElement("i"); more.textContent = "…"; mini.appendChild(more); }
            go.className = "lp-zoom-go"; go.textContent = "放大";
            row.appendChild(go);
            box.appendChild(mini);
            box.addEventListener("click", function () { into(kid, box); });
          }
          kidsBox.appendChild(box);
        });
        figure.setAttribute("data-depth", String(depth));
        ui.decorate(view);
        ui.layout();
      };
      /* 放大与退回：一块不带字的“影子”从部件长到新一层的画面（或反过来），字不会被拉伸；影子落定后新一层淡入。 */
      var ghost = function (from, to, done) {
        var base = view.getBoundingClientRect(), shadow = document.createElement("div");
        shadow.className = "lp-zoom-ghost"; shadow.setAttribute("aria-hidden", "true");
        view.appendChild(shadow);
        var at = function (r) { return { left: (r.left - base.left) + "px", top: (r.top - base.top) + "px", width: r.width + "px", height: r.height + "px" }; };
        busy = true;
        shadow.animate([at(from), at(to)], { duration: 420, easing: "cubic-bezier(.2,.7,.2,1)", fill: "forwards" }).onfinish = function () {
          busy = false;
          done();
          shadow.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 240, fill: "forwards" }).onfinish = function () { shadow.remove(); };
          /* 动画途中要退回（Esc、上一层、外圈的名字）：记着，落定后再退 */
          if (queued) { var depth = queued; queued = 0; back(depth); }
        };
      };
      var still = function () { return ui.reduceMotion || !frame.animate; };
      /* 换层时原来的按钮被换掉，焦点先停在一直在场的画面上，动画结束再交给新一层的标题或原来那块；
         读者在动画途中已经把焦点挪走了，就不再抢回来。 */
      var hold = function () { var at = document.activeElement; if (!at || at === document.body || view.contains(at)) view.focus({ preventScroll: true }); };
      var pass = function (el) { if (document.activeElement === view) el.focus({ preventScroll: true }); };
      var into = function (kid, box) {
        if (busy) return;
        var from = box.getBoundingClientRect();
        trail.push(kid);
        draw();
        hold();
        var settle = function () { pass(title); };
        if (still()) { settle(); return; }
        frame.classList.add("is-moving");
        ghost(from, here.getBoundingClientRect(), function () {
          frame.classList.remove("is-moving");
          frame.animate([{ opacity: 0.4 }, { opacity: 1 }], { duration: 240, easing: "ease-out" });
          settle();
        });
      };
      var back = function (depth) {
        if (depth >= trail.length || depth < 1) return;
        if (busy) { queued = depth; return; }
        var leaving = trail[depth], from = here.getBoundingClientRect();
        trail = trail.slice(0, depth);
        draw();
        hold();
        var box = kidsBox.children[trail[trail.length - 1].kids.indexOf(leaving)];
        if (!box) { pass(title); return; }
        box.classList.add("is-from");
        window.setTimeout(function () { box.classList.remove("is-from"); }, 1400);
        if (still()) { pass(box); return; }
        kidsBox.style.visibility = "hidden";
        ghost(from, box.getBoundingClientRect(), function () { kidsBox.style.visibility = ""; pass(box); });
      };
      up.addEventListener("click", function () { back(trail.length - 1); });
      view.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && trail.length > 1) { back(trail.length - 1); event.preventDefault(); event.stopPropagation(); }
      });
      view.setAttribute("tabindex", "-1");
      figure.classList.add("is-ready");
      draw();
    } catch (error) { ui.failed(figure, error); }
  });
} });
