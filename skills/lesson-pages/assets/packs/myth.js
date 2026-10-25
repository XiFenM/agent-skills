/* lesson-pages 部件包：误区对照 .lp-myth。由 lesson_pages.py 写进用到它的页面，页面不要修改本段。
   误解先完整读一遍，滚到时被一笔划掉；没有脚本或减少动态效果时直接显示划线。 */
(window.LessonPage.packs = window.LessonPage.packs || []).push({ name: "myth", init: function (ui) {
  ui.$all(".lp-myth").forEach(function (card) {
    try {
      var wrong = card.querySelector(":scope > .lp-myth-wrong");
      if (!wrong) return;
      var strike = document.createElement("span");
      strike.className = "lp-myth-strike";
      while (wrong.firstChild) strike.appendChild(wrong.firstChild);
      wrong.appendChild(strike);
      ui.inView(card, function () { window.setTimeout(function () { card.classList.add("is-struck"); }, 450); }, "0px 0px -30% 0px");
      window.addEventListener("beforeprint", function () { card.classList.add("is-struck"); });
    } catch (error) { ui.failed(card, error); }
  });
} });
