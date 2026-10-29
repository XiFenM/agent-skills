/* lesson-pages 部件包：声明式源码浏览器 .lp-source-tree。由 lesson_pages.py 注入，不手改生成副本。
   作者只写仓库元信息与带 id/data-kind/data-path 的嵌套提纲；运行时生成目录、说明、控件和辅助连线。
   节点 id 留在原 li 上；定位只滚动目录容器，不滚动整页。无脚本与打印保留完整提纲。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "source-tree", init: function (ui) {
  var NS = "http://www.w3.org/2000/svg";
  var make = function (tag, cls, text) {
    var el = document.createElement(tag); if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text; return el;
  };
  var button = function (text) { var b = make("button", "lp-btn", text); b.type = "button"; return b; };
  var icon = function (folder) {
    var svg = document.createElementNS(NS, "svg"), path = document.createElementNS(NS, "path");
    svg.setAttribute("class", "lp-st-icon"); svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true"); svg.setAttribute("focusable", "false");
    path.setAttribute("d", folder ? "M3 6h7l2 3h9v11H3zM3 9h18" : "M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6");
    svg.appendChild(path); return svg;
  };
  var clone = function (el) {
    var copy = el.cloneNode(true); copy.removeAttribute("id");
    ui.$all("[id]", copy).forEach(function (child) { child.removeAttribute("id"); });
    copy.classList.remove("lp-st-source-text", "lp-st-source-links"); return copy;
  };
  ui.$all(".lp-source-tree").forEach(function (figure) {
    if (figure.classList.contains("is-ready")) return;
    try {
      var map = Object.create(null), repos = [], active = null, frame = 0;
      var read = function (li, parent, repo) {
        var kind = li.getAttribute("data-kind"), path = li.getAttribute("data-path");
        var name = li.querySelector(":scope > b"), text = li.querySelector(":scope > p");
        if (!li.id || map[li.id] || !path || !name || !text || ["dir", "file", "context"].indexOf(kind) < 0)
          throw new Error("源码节点需要唯一 id、data-kind、data-path，以及直接子 b 和 p");
        var node = { id: li.id, path: path, kind: kind, name: name, text: text, el: li,
          parent: parent, repo: repo, kids: [], main: li.getAttribute("data-main") === "true", row: null, details: null };
        map[node.id] = node; repo.nodes.push(node);
        var sub = li.querySelector(":scope > ul:not(.lp-source-links)");
        node.links = li.querySelector(":scope > ul.lp-source-links");
        if (kind === "dir") {
          if (!sub || node.links) throw new Error("目录节点需要一个子节点 ul，不能使用文件源码链接表");
          node.kids = ui.$all(":scope > li", sub).map(function (child) { return read(child, node, repo); });
          if (!node.kids.length) throw new Error("未展开的旁支目录请使用 data-kind=context");
        } else if (sub || (kind === "file" && (!node.links || !node.links.querySelector("a[href]")))) {
          throw new Error("文件需要 lp-source-links；文件和旁支不能含子节点");
        }
        return node;
      };
      ui.$all(":scope > .lp-source-repo", figure).forEach(function (el) {
        var head = el.querySelector(":scope > h4"), outline = el.querySelector(":scope > ul.lp-source-outline");
        if (!el.id || !head || !outline || !el.querySelector(":scope > .lp-source-version") || !el.querySelector(":scope > .lp-source-about"))
          throw new Error("源码仓库需要 id、h4、版本、说明和 lp-source-outline");
        var repo = { el: el, title: ui.plainText(head), outline: outline, nodes: [], roots: [] };
        repo.roots = ui.$all(":scope > li", outline).map(function (li) { return read(li, null, repo); });
        if (!repo.nodes.length) throw new Error("源码仓库至少需要一个节点");
        var start = el.getAttribute("data-start");
        repo.start = start ? map[start] : repo.nodes.filter(function (n) { return n.main; })[0] || repo.nodes.filter(function (n) { return n.kind === "file"; })[0] || repo.nodes[0];
        if (!repo.start || repo.start.repo !== repo) throw new Error("data-start 必须指向本仓库的节点 id");
        repo.selected = repo.start; repos.push(repo);
      });
      if (!repos.length) throw new Error("源码浏览器至少需要一个 lp-source-repo");

      var tabs = make("div", "lp-st-tabs"), status = make("p", "lp-st-status");
      tabs.setAttribute("role", "group"); tabs.setAttribute("aria-label", "源码仓库");
      status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
      figure.insertBefore(tabs, repos[0].el); figure.insertBefore(status, repos[0].el);
      var draw = function () {
        frame = 0; if (!active) return;
        var repo = active, base = repo.work.getBoundingClientRect(), left = repo.tree.getBoundingClientRect();
        var right = repo.info.getBoundingClientRect(), row = repo.selected.row.getBoundingClientRect();
        var head = repo.info.querySelector("h5").getBoundingClientRect();
        var stacked = right.top >= left.bottom - 2;
        var hideWire = stacked || !row.width || row.bottom <= left.top || row.top >= left.bottom || base.width === 0;
        repo.wire.toggleAttribute("hidden", hideWire);
        if (hideWire) return;
        var x1 = left.right - base.left + 2, x2 = right.left - base.left - 2;
        var y1 = Math.max(left.top + 3, Math.min(left.bottom - 3, row.top + row.height / 2)) - base.top;
        var y2 = head.top + head.height / 2 - base.top, mid = (x1 + x2) / 2;
        repo.wire.setAttribute("viewBox", "0 0 " + base.width + " " + base.height);
        repo.line.setAttribute("d", "M" + x1 + " " + y1 + "C" + mid + " " + y1 + " " + mid + " " + y2 + " " + x2 + " " + y2);
        repo.dots.forEach(function (dot, i) { dot.setAttribute("cx", i ? x2 : x1); dot.setAttribute("cy", i ? y2 : y1); });
      };
      var schedule = function () { if (!frame) frame = window.requestAnimationFrame(draw); };
      /* 只改变内部滚动位置。scrollIntoView 会顺带滚动页面，不用于目录定位或连线。 */
      var reveal = function (node) {
        var p = node.parent; while (p) { p.details.open = true; p = p.parent; }
        var pane = node.repo.tree, box = pane.getBoundingClientRect(), row = node.row.getBoundingClientRect();
        if (row.top < box.top + 6) pane.scrollTop += row.top - box.top - 6;
        else if (row.bottom > box.bottom - 6) pane.scrollTop += row.bottom - box.bottom + 6;
      };
      var choose = function (node, locate) {
        var repo = node.repo; repo.selected = node;
        repo.nodes.forEach(function (n) { n.row.classList.toggle("is-selected", n === node); n.row.removeAttribute("aria-current"); n.row.classList.remove("is-path"); });
        node.row.setAttribute("aria-current", "true");
        var parents = [], p = node.parent;
        while (p) { parents.unshift(p); p.row.classList.add("is-path"); p = p.parent; }
        repo.info.textContent = "";
        var kind = make("p", "lp-st-kind", node.kind === "file" ? "文件" : node.kind === "context" ? "旁支目录" : "目录");
        var head = make("h5", "lp-st-title", ui.plainText(node.name));
        var path = make("p", "lp-st-path"); path.appendChild(make("code", "", node.path));
        repo.info.appendChild(kind); repo.info.appendChild(head); repo.info.appendChild(path);
        var description = clone(node.text); description.classList.add("lp-st-description"); repo.info.appendChild(description);
        if (node.links) { var links = clone(node.links); links.classList.add("lp-st-links"); repo.info.appendChild(links); }
        var nav = make("div", "lp-st-related");
        var addLink = function (target, text) {
          var b = button(text); b.addEventListener("click", function () { choose(target, true); target.row.focus({ preventScroll: true }); }); nav.appendChild(b);
        };
        if (node.parent) addLink(node.parent, "上级：" + ui.plainText(node.parent.name));
        node.kids.forEach(function (kid) { addLink(kid, ui.plainText(kid.name)); });
        if (nav.childNodes.length) { nav.setAttribute("aria-label", "相关目录与文件"); repo.info.appendChild(nav); }
        if (locate) reveal(node);
        status.textContent = repo.title + " · " + node.path;
        schedule();
      };
      var activate = function (repo, locate) {
        active = repo;
        repos.forEach(function (r) { r.el.hidden = r !== repo; r.tab.setAttribute("aria-pressed", String(r === repo)); });
        choose(repo.selected, locate); ui.layout();
      };
      repos.forEach(function (repo, index) {
        var tab = button(repo.title); tab.setAttribute("aria-controls", repo.el.id); tab.setAttribute("aria-pressed", "false");
        tab.addEventListener("click", function () { activate(repo, false); }); tabs.appendChild(tab); repo.tab = tab;
        var work = make("div", "lp-st-workspace"), pane = make("div", "lp-st-tree-pane");
        var bar = make("div", "lp-st-bar"), label = make("span", "", "文件目录"), controls = make("div", "lp-st-actions");
        var expand = button("展开"), collapse = button("折叠"), locate = button("定位主线");
        controls.appendChild(expand); controls.appendChild(collapse);
        if (repo.nodes.some(function (n) { return n.main; }) || repo.el.hasAttribute("data-start")) controls.appendChild(locate);
        bar.appendChild(label); bar.appendChild(controls); pane.appendChild(bar);
        var tree = make("div", "lp-st-tree"), info = make("div", "lp-st-info");
        tree.tabIndex = 0; tree.setAttribute("role", "region"); tree.setAttribute("aria-label", repo.title + "文件目录");
        info.setAttribute("role", "region"); info.setAttribute("aria-label", repo.title + "选中路径说明");
        var infoId = figure.id + "-source-info-" + index;
        while (document.getElementById(infoId)) infoId += "-view";
        info.id = infoId;
        repo.el.insertBefore(work, repo.outline); tree.appendChild(repo.outline); pane.appendChild(tree); work.appendChild(pane); work.appendChild(info);
        var jump = make("a", "lp-st-info-jump", "查看所选路径说明");
        jump.href = "#" + infoId; jump.setAttribute("aria-label", "查看" + repo.title + "所选路径的说明"); pane.appendChild(jump);
        repo.work = work; repo.tree = tree; repo.info = info;
        var wire = document.createElementNS(NS, "svg"), line = document.createElementNS(NS, "path");
        wire.setAttribute("class", "lp-st-wire"); wire.setAttribute("aria-hidden", "true"); wire.setAttribute("focusable", "false");
        wire.appendChild(line); repo.dots = [2.5, 3.5].map(function (r) { var dot = document.createElementNS(NS, "circle"); dot.setAttribute("r", r); wire.appendChild(dot); return dot; });
        work.appendChild(wire); repo.wire = wire; repo.line = line;
        repo.nodes.forEach(function (node) {
          var row;
          if (node.kind === "dir") {
            var details = make("details", "lp-st-directory"); row = make("summary", "lp-st-row");
            details.appendChild(row); node.details = details;
            while (node.el.firstChild) details.appendChild(node.el.firstChild);
            node.el.appendChild(details);
          } else { row = make("a", "lp-st-row"); row.href = "#" + node.id; node.el.insertBefore(row, node.el.firstChild); }
          row.appendChild(icon(node.kind !== "file")); row.appendChild(node.name);
          row.setAttribute("data-source-node", node.id); row.setAttribute("aria-controls", infoId); row.title = node.path;
          node.row = row; node.text.classList.add("lp-st-source-text");
          if (node.links) node.links.classList.add("lp-st-source-links");
          if (node.kind === "context") node.el.classList.add("lp-st-context");
          if (node.main) { node.el.classList.add("lp-st-main"); var badge = make("span", "lp-st-main-label", "主线"); row.appendChild(badge); }
          row.addEventListener("click", function (event) {
            if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return;
            if (row.tagName === "A") event.preventDefault(); choose(node, false);
          });
        });
        expand.addEventListener("click", function () { repo.nodes.forEach(function (n) { if (n.details) n.details.open = true; }); schedule(); });
        collapse.addEventListener("click", function () { repo.nodes.forEach(function (n) { if (n.details) n.details.open = false; }); choose(repo.roots[0], false); });
        locate.addEventListener("click", function () { choose(repo.start, true); repo.start.row.focus({ preventScroll: true }); });
        tree.addEventListener("scroll", schedule, { passive: true });
        tree.addEventListener("toggle", schedule, true);
        if (window.ResizeObserver) new ResizeObserver(schedule).observe(work);
      });
      tabs.addEventListener("keydown", function (event) {
        var i = repos.map(function (r) { return r.tab; }).indexOf(document.activeElement), next;
        if (i < 0) return;
        if (event.key === "ArrowRight") next = (i + 1) % repos.length;
        else if (event.key === "ArrowLeft") next = (i + repos.length - 1) % repos.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = repos.length - 1;
        else return;
        event.preventDefault(); activate(repos[next], false); repos[next].tab.focus({ preventScroll: true });
      });
      var hashNode = function () { try { return map[decodeURIComponent(window.location.hash.slice(1))]; } catch (error) { return null; } };
      var followHash = function () { var n = hashNode(); if (n) { n.repo.selected = n; activate(n.repo, true); } };
      window.addEventListener("hashchange", followHash);
      window.addEventListener("resize", schedule);
      document.addEventListener("lp:layout", schedule);
      if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
      var printState = null;
      window.addEventListener("beforeprint", function () {
        if (printState) return;
        printState = []; repos.forEach(function (r) { r.nodes.forEach(function (n) { if (n.details) { printState.push([n.details, n.details.open]); n.details.open = true; } }); });
      });
      window.addEventListener("afterprint", function () { (printState || []).forEach(function (s) { s[0].open = s[1]; }); printState = null; schedule(); });
      figure.classList.add("is-stage", "is-ready");
      repos.forEach(function (r) { var p = r.start.parent; while (p) { p.details.open = true; p = p.parent; } });
      var initial = hashNode(); if (initial) initial.repo.selected = initial;
      activate(initial ? initial.repo : repos[0], true);
    } catch (error) { ui.failed(figure, error); }
  });
} });
