/* lesson-pages 部件包：声明式时序图 .lp-timeline。由 lesson_pages.py 写入用到它的页面。
   复用 lp-stepper 的按钮、跳步与键盘；每步是完整快照，不执行作者提供的业务脚本。
   model 是有来源的因果模型，observed 是实测轨迹；二者都须在 figcaption 交代依据。
   initSteppers 先于 initPacks：注册 onStep 后主动按 data-step 渲染一次。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "timeline", init: function (ui) {
  var LP = window.LessonPage;
  var statuses = { idle: "空闲", writing: "写入中", ready: "就绪", reading: "读取中", waiting: "等待", done: "已完成" };
  var keyPattern = /^[A-Za-z][A-Za-z0-9_-]*$/;
  var text = function (parent, selector) {
    var matches = ui.$all(selector, parent);
    if (matches.length !== 1 || !matches[0].textContent.trim()) throw new Error("时序图需要一个非空的 " + selector);
    return matches[0].textContent.trim();
  };
  var element = function (tag, className, value) {
    var el = document.createElement(tag);
    el.className = className;
    if (value !== undefined) el.textContent = value;
    return el;
  };
  ui.$all(".lp-timeline").forEach(function (figure) {
    if (figure.classList.contains("is-timeline-ready")) return;
    var board = null;
    try {
      var kind = figure.getAttribute("data-timeline-kind");
      if (!figure.id || !figure.classList.contains("lp-stepper")) throw new Error("时序图需要 id 和 lp-stepper");
      if (kind !== "model" && kind !== "observed") throw new Error("data-timeline-kind 只能是 model 或 observed");
      if (typeof LP.onStep[figure.id] === "function") throw new Error("时序图自动管理 onStep，不要为它另写脚本");
      var canvases = ui.$all(":scope > .lp-canvas", figure);
      var lists = ui.$all(":scope > ol.lp-steps", figure);
      if (canvases.length !== 1 || lists.length !== 1) throw new Error("时序图需要一个直接子级 lp-canvas 和 ol.lp-steps");
      var canvas = canvases[0], list = lists[0], nodes = ui.$all(":scope > li", list);
      if (nodes.length < 2) throw new Error("时序图至少需要两步");
      text(figure, ":scope > figcaption");
      var actors = [], actorByKey = Object.create(null), definitions = [], pairs = Object.create(null);
      var snapshots = nodes.map(function (node, index) {
        var title = (node.getAttribute("data-title") || "").trim();
        if (!title) throw new Error("时序图每步需要 data-title");
        var stateLists = ui.$all(":scope > ul.lp-timeline-state", node);
        if (stateLists.length !== 1) throw new Error("时序图每步需要一个完整的 ul.lp-timeline-state");
        var rows = ui.$all(":scope > li", stateLists[0]), cells = Object.create(null);
        rows.forEach(function (row) {
          var actor = row.getAttribute("data-actor") || "", slot = row.getAttribute("data-slot") || "";
          var status = row.getAttribute("data-status") || "", pair = actor + "/" + slot;
          if (!keyPattern.test(actor) || !keyPattern.test(slot)) throw new Error("data-actor 和 data-slot 须使用以字母开头的短标识");
          if (!Object.prototype.hasOwnProperty.call(statuses, status)) throw new Error("未知的时序图状态：" + status);
          if (cells[pair]) throw new Error("同一步重复了参与者与槽位：" + pair);
          var owner = text(row, ":scope > .lp-timeline-owner"), label = text(row, ":scope > .lp-timeline-slot");
          var value = text(row, ":scope > .lp-timeline-value"), signal = text(row, ":scope > .lp-timeline-signal");
          if (!index) {
            if (!actorByKey[actor]) {
              actorByKey[actor] = { key: actor, label: owner, slots: [] };
              actors.push(actorByKey[actor]);
            }
            if (actorByKey[actor].label !== owner) throw new Error("同一参与者的显示名不一致：" + actor);
            var definition = { key: pair, actor: actor, slot: slot, owner: owner, label: label };
            pairs[pair] = definition; definitions.push(definition); actorByKey[actor].slots.push(definition);
          } else if (!pairs[pair] || pairs[pair].owner !== owner || pairs[pair].label !== label) {
            throw new Error("时序图各步必须使用相同的参与者、槽位与显示名：" + pair);
          }
          cells[pair] = { status: status, value: value, signal: signal };
        });
        if (rows.length !== definitions.length || definitions.some(function (d) { return !cells[d.key]; })) {
          throw new Error("时序图每步须列出全部槽位，不能用省略值继承上一步");
        }
        return { title: title, event: text(node, ":scope > .lp-timeline-event"), dependency: text(node, ":scope > .lp-timeline-dependency"), cells: cells };
      });
      if (actors.length < 2) throw new Error("时序图至少需要两个参与者");

      board = element("div", "lp-timeline-board");
      board.setAttribute("role", "group"); board.setAttribute("aria-label", "参与者与槽位状态");
      var heading = element("div", "lp-timeline-heading");
      heading.appendChild(element("span", "lp-timeline-kind", kind === "model" ? "因果模型" : "实测轨迹"));
      var current = element("h4", "lp-timeline-current"); heading.appendChild(current); board.appendChild(heading);
      var event = element("p", "lp-timeline-now"); event.setAttribute("aria-live", "polite"); event.setAttribute("aria-atomic", "true");
      board.appendChild(event);
      var grid = element("div", "lp-timeline-actors"), rendered = Object.create(null);
      actors.forEach(function (actor) {
        var panel = element("section", "lp-timeline-actor");
        panel.setAttribute("data-actor", actor.key); panel.setAttribute("aria-label", actor.label);
        panel.appendChild(element("h5", "lp-timeline-actor-name", actor.label));
        var slots = element("div", "lp-timeline-slots");
        actor.slots.forEach(function (definition) {
          var cell = element("div", "lp-timeline-cell"), head = element("div", "lp-timeline-cell-head");
          cell.setAttribute("data-slot", definition.slot);
          head.appendChild(element("b", "lp-timeline-cell-name", definition.label));
          var status = element("span", "lp-timeline-status"); head.appendChild(status); cell.appendChild(head);
          var value = element("p", "lp-timeline-cell-value"), signal = element("p", "lp-timeline-cell-signal");
          cell.appendChild(value); cell.appendChild(signal); slots.appendChild(cell);
          rendered[definition.key] = { el: cell, status: status, value: value, signal: signal };
        });
        panel.appendChild(slots); grid.appendChild(panel);
      });
      board.appendChild(grid);
      var dependency = element("div", "lp-timeline-gate");
      dependency.appendChild(element("b", "lp-timeline-gate-label", "依赖与等待"));
      var gate = element("p", "lp-timeline-gate-text"); dependency.appendChild(gate); board.appendChild(dependency);
      canvas.appendChild(board);
      var render = function (step) {
        var snapshot = snapshots[step - 1];
        if (!snapshot) throw new Error("时序图步号超出范围");
        current.textContent = "第 " + step + " / " + snapshots.length + " 步 · " + snapshot.title;
        event.textContent = snapshot.event; gate.textContent = snapshot.dependency;
        definitions.forEach(function (definition) {
          var cell = rendered[definition.key], state = snapshot.cells[definition.key];
          cell.el.setAttribute("data-status", state.status);
          cell.status.textContent = statuses[state.status]; cell.value.textContent = state.value;
          cell.signal.textContent = "信号／条件：" + state.signal;
        });
      };
      /* 完整快照决定所有显示值；直接跳到第N步与逐步走到N的结果相同。 */
      var initial = Number(figure.getAttribute("data-step")) || 1;
      render(Math.max(1, Math.min(snapshots.length, initial)));
      LP.onStep[figure.id] = function (step) { render(step); };
      figure.classList.add("is-timeline-ready");
      var controls = figure.querySelector(":scope > .lp-controls");
      if (controls) figure.insertBefore(controls, canvas);
      /* 基础stepper键盘事件只从子控件冒泡时生效；容器也可直接Tab聚焦。 */
      if (figure.getAttribute("tabindex") === "-1") figure.setAttribute("tabindex", "0");
      ui.recovered(figure); ui.layout();
    } catch (error) {
      if (board && board.parentNode) board.remove();
      figure.classList.remove("is-timeline-ready");
      ui.failed(figure, error);
    }
  });
} });
