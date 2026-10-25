/* lesson-pages 部件包：类比卡 .lp-analogy。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   先读类比；按下按钮，卡片沿一道裂口展开，露出类比在哪里不成立。没有脚本、打印时两部分都显示。
   类比正文里紧跟在词后的短括注，如“桌面（片上存储）”，是类比与实物的对应：画成一枚“≈ 片上存储”的小签，
   一眼看出每样东西对应什么。括注带标点、数字或以“如、比如、约”等开头时不是对应，原样保留。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "analogy", init: function (ui) {
  var GLOSS = /（([^（），。、；：！？,.;:!?0-9０-９]{1,10})）/g, ASIDE = /^(如|比如|例如|即|也|或|约|见|注|指)/;
  var tagPairs = function (paragraph) {
    var walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT), texts = [];
    while (walker.nextNode()) if (!walker.currentNode.parentNode.closest("code, .katex, .tex, ruby, a")) texts.push(walker.currentNode);
    texts.forEach(function (node) {
      var text = node.nodeValue, last = 0, out = document.createDocumentFragment(), found = false, m;
      GLOSS.lastIndex = 0;
      while ((m = GLOSS.exec(text))) {
        var before = m.index ? text.charAt(m.index - 1) : node.previousSibling ? "x" : " ";
        if (/\s/.test(before) || ASIDE.test(m[1])) continue;
        found = true;
        out.appendChild(document.createTextNode(text.slice(last, m.index)));
        var tag = document.createElement("span");
        tag.className = "lp-analogy-map";
        tag.innerHTML = '<span class="lp-visually-hidden">（</span><span></span><span class="lp-visually-hidden">）</span>';
        tag.children[1].textContent = m[1];
        out.appendChild(tag);
        last = m.index + m[0].length;
      }
      if (!found) return;
      out.appendChild(document.createTextNode(text.slice(last)));
      node.parentNode.replaceChild(out, node);
    });
  };
  ui.$all(".lp-analogy").forEach(function (card, index) {
    try {
      ui.$all(":scope > p", card).forEach(tagPairs);
      var limit = card.querySelector(":scope > .lp-analogy-limit");
      if (!limit) return;
      if (!limit.id) limit.id = (card.id || "lp-analogy-" + (index + 1)) + "-limit";
      var button = document.createElement("button");
      button.type = "button"; button.className = "lp-analogy-open";
      button.setAttribute("aria-controls", limit.id);
      var set = function (open) {
        limit.hidden = !open;
        card.classList.toggle("is-open", open);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        button.textContent = open ? "收起" : "这个类比在哪里不成立？";
      };
      card.insertBefore(button, limit);
      set(false);
      button.addEventListener("click", function () { set(limit.hidden); ui.layout(); });
      window.addEventListener("beforeprint", function () { limit.hidden = false; });
      window.addEventListener("afterprint", function () { limit.hidden = !card.classList.contains("is-open"); });
    } catch (error) { ui.failed(card, error); }
  });
} });
