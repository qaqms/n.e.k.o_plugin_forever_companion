// 拟真书本样式（1.3.0 日记页重做）：个人日记 = 她手写的线装本，我的日记 = 第三方留下的
// 铅印卷宗。两本共用「书脊列 + 纸页 + sticky 页脚」的骨架，性格靠字体/纸色/装订细节分岔。
//
// 为什么不塞进 styles.ts：styles.ts（89KB）是"面板公共玻璃层"，这一坨是"桌面物件层"——
// 纸/墨/装订/木架的调色板互不相通，混在一起后面谁也不敢删。单独一个模块 + 第二个
// <style> 标签（diary.tsx 内联挂），归属清楚，也保住 hosted 依赖预算的可预测性。
//
// 硬约束（都来自宿主 hosted-tsx 运行时，别试着想绕）：
//   1. 无 SVG：装订孔/丝带/朱印一律用 background-image + clip-path 画（同 ring.tsx 先例）
//   2. 纸面**不能** overflow:hidden——它会变成 sticky 页脚的滚动容器，把"常驻下缘"
//      当场废掉；所以丝带/页脚外扩一律靠 clip-path 自剪，不靠父级裁
//   3. 半透明 sticky 页脚在"纸叠"上会露馅（文字从半透区穿过去），所以页脚底色用
//      实色渐变 + 不画圆角（页脚即页面收口），只保留毛玻璃模糊这一处
//   4. 颜色写死在本文件（含暗色孪生块），不走面板 --tm-* 外观变量：面板「背景调节」
//      管的是玻璃卡片，不该把手写的纸也一起调淡
export const BOOK_STYLES = `

/* ============================================================
   0. 书本调色板（局部变量，只活在本模块的选择器里）
   ============================================================ */
.tmb-book, .tmb-shelf {
  --tmb-kai: "KaiTi", "STKaiti", "Kaiti SC", "BiauKai", "DFKai-SB", "Noto Serif SC", "Songti SC", "SimSun", serif;
  --tmb-song: "Songti SC", "SimSun", "NSimSun", "Noto Serif SC", "Georgia", serif;
  --tmb-print: "Georgia", "Times New Roman", "Songti SC", "SimSun", serif;
  --tmb-mono: ui-monospace, "Cascadia Mono", "Menlo", Consolas, "Courier New", monospace;
  --tmb-paper-hi: #fdfaf1;
  --tmb-paper-mid: #f8f2e3;
  --tmb-paper-lo: #f1e9d5;
  --tmb-paper-edge: rgba(198, 178, 142, 0.62);
  --tmb-ink: #3a3122;
  --tmb-ink-soft: rgba(120, 102, 68, 0.92);
  --tmb-rule: rgba(150, 128, 92, 0.34);
  --tmb-cloth: #6b4f36;
  --tmb-cloth-lo: #4a3524;
  --tmb-ribbon: #a8413a;
  --tmb-file-paper-hi: #f7f8fa;
  --tmb-file-paper-lo: #e9edf2;
  --tmb-file-edge: rgba(120, 132, 150, 0.46);
  --tmb-file-ink: #2d333b;
  --tmb-file-rule: rgba(72, 86, 104, 0.42);
  --tmb-seal: rgba(170, 54, 42, 0.78);
}

/* ============================================================
   1. 书架：目录视图（书脊一排，点一根抽出那页）
   ============================================================ */
/* 书脊是"站着的书"，不是卡片：横向排、底边坐在一根木隔板上。
   木隔板挂在 .tmb-shelf::after（真元素不行——它得跟着行高走），
   换行时行与行之间留足气口，读作"两层书架"而不是一排按钮 */
.tmb-shelf {
  display: flex; flex-wrap: wrap; align-items: flex-end; gap: 5px 6px;
  padding: 18px 8px 14px; margin: 0 -6px;
}
.tmb-shelf { position: relative; }
.tmb-shelf::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: 5px; height: 7px;
  border-radius: 2px;
  background: linear-gradient(180deg, rgba(150, 116, 74, 0.55) 0%, rgba(108, 80, 48, 0.42) 55%, rgba(70, 52, 32, 0.30) 100%);
  box-shadow: 0 4px 9px rgba(70, 50, 28, 0.20), inset 0 1px 0 rgba(255, 246, 226, 0.35);
}

.tmb-spine {
  position: relative; flex: 0 0 auto;
  width: 34px; height: 186px; padding: 8px 0 9px;
  display: flex; flex-direction: column; align-items: center; gap: 4px;
  border: 1px solid rgba(58, 42, 24, 0.34); border-radius: 3px 3px 2px 2px;
  /* 布面书脊：中间一道高光（圆柱感）+ 两端压暗，纸基色由 --tmb-spine-base 给
     （= 当期心情均值 moodDotColor，近零自动落灰，与全站心情语义同一口径） */
  background-image:
    linear-gradient(90deg, rgba(28, 18, 8, 0.34) 0%, rgba(255, 252, 240, 0.30) 32%, rgba(255, 255, 255, 0.10) 52%, rgba(28, 18, 8, 0.30) 100%),
    repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.055) 0 1px, rgba(0, 0, 0, 0.045) 1px 3px);
  background-color: var(--tmb-spine-base, rgba(148, 163, 184, 0.6));
  box-shadow: 2px 4px 9px rgba(46, 32, 16, 0.26), inset -3px 0 6px rgba(24, 16, 6, 0.28), inset 3px 0 5px rgba(255, 250, 236, 0.20);
  cursor: pointer;
  transition: transform 0.18s cubic-bezier(0.22, 0.61, 0.36, 1), box-shadow 0.18s ease;
}
/* 抽出来一点：整根上移 + 影子拉长（悬停即"这本可以拿"） */
.tmb-spine:hover {
  transform: translateY(-12px);
  box-shadow: 2px 14px 20px rgba(46, 32, 16, 0.30), inset -3px 0 6px rgba(24, 16, 6, 0.28), inset 3px 0 5px rgba(255, 250, 236, 0.24);
}
.tmb-spine:focus-visible { outline: 2px solid rgba(200, 150, 90, 0.9); outline-offset: 2px; }
/* 书顶：纸上沿露出的一线（斜切圆角让整排书顶不是一条直线） */
.tmb-spine-top {
  width: 24px; height: 4px; border-radius: 1px 2px 0 0;
  background: linear-gradient(180deg, rgba(252, 248, 236, 0.95), rgba(226, 214, 188, 0.8));
  box-shadow: 0 1px 0 rgba(58, 42, 24, 0.22);
}
/* 页码方块（横排，压在书脊顶端） */
.tmb-spine-no {
  width: 22px; height: 17px; margin-top: 3px;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 2px; background: rgba(252, 247, 234, 0.92);
  box-shadow: inset 0 0 0 1px rgba(58, 42, 24, 0.22);
  font-size: 10px; font-weight: 700; letter-spacing: 0; color: #4a3722;
}
/* 竖排日期区间：书脊上的字本来就该竖着写 */
.tmb-spine-date {
  writing-mode: vertical-rl; text-orientation: mixed;
  margin-top: 7px; font-size: 11px; line-height: 1.1; letter-spacing: 0.04em;
  color: rgba(252, 246, 230, 0.95);
  text-shadow: 0 1px 1px rgba(20, 12, 4, 0.5);
  max-height: 104px; overflow: hidden;
}
.tmb-spine-spacer { flex: 1 1 auto; min-height: 0; }
/* 书根：段数（她的话多不多）——压在木隔板上那一端 */
.tmb-spine-foot {
  writing-mode: vertical-rl; text-orientation: mixed;
  font-size: 9.5px; letter-spacing: 0.02em; color: rgba(250, 244, 228, 0.78);
  text-shadow: 0 1px 1px rgba(20, 12, 4, 0.45);
}
/* 旧版迁移页：一枚贴在脊上的小标签 */
.tmb-spine-flag {
  position: absolute; top: 44%; left: 2px; right: 2px;
  padding: 1px 0; border-radius: 1px; text-align: center;
  background: rgba(176, 132, 66, 0.92); color: #fffaf0;
  font-size: 8.5px; line-height: 1.5; letter-spacing: 0.06em;
  box-shadow: 0 1px 2px rgba(28, 18, 8, 0.4);
}

/* ---- 我的日记：档案盒脊（同一根骨架，换配色与字体）---- */
.tmb-spine--file {
  width: 31px; height: 168px;
  border-color: rgba(38, 46, 58, 0.42); border-radius: 2px;
  background-image:
    linear-gradient(90deg, rgba(14, 20, 28, 0.30) 0%, rgba(255, 255, 255, 0.24) 34%, rgba(255, 255, 255, 0.06) 54%, rgba(14, 20, 28, 0.26) 100%),
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.05) 0 1px, rgba(0, 0, 0, 0.04) 1px 4px);
  background-color: #7e8794;
  box-shadow: 2px 4px 9px rgba(18, 26, 36, 0.28), inset -3px 0 6px rgba(10, 16, 24, 0.26), inset 3px 0 5px rgba(255, 255, 255, 0.16);
}
.tmb-spine--file:hover { box-shadow: 2px 14px 20px rgba(18, 26, 36, 0.32), inset -3px 0 6px rgba(10, 16, 24, 0.26), inset 3px 0 5px rgba(255, 255, 255, 0.18); }
.tmb-spine--file .tmb-spine-top { background: linear-gradient(180deg, rgba(240, 244, 248, 0.95), rgba(206, 214, 224, 0.8)); box-shadow: 0 1px 0 rgba(38, 46, 58, 0.3); }
.tmb-spine--file .tmb-spine-no { background: rgba(246, 248, 251, 0.95); color: #33404f; box-shadow: inset 0 0 0 1px rgba(38, 46, 58, 0.24); width: 27px; font-size: 9.5px; }
.tmb-spine--file .tmb-spine-date { font-family: var(--tmb-mono); font-size: 10px; letter-spacing: -0.02em; color: rgba(250, 252, 255, 0.94); }
.tmb-spine--file .tmb-spine-foot { font-family: var(--tmb-mono); font-size: 9px; color: rgba(248, 250, 253, 0.72); }

/* 书架空态/加载中的一句小字由现有 .tm-derived 承担，不另立样式 */

/* ============================================================
   2. 书：书脊列 + 纸页 + sticky 页脚
   ============================================================ */
.tmb-book {
  display: grid; grid-template-columns: 27px minmax(0, 1fr);
  align-items: stretch; max-width: var(--tmb-col, 640px); margin: 2px auto 0;
}
/* 1.3.0 真机反馈“全屏下书很扁”：纸页实测 728×366 ≈ 2.0:1。宽收到 640
   （正文列 ≈ 540px → 15px 下约 36 字/行，中文书舒适行宽），高见 .tmb-page
   竖版下限。列宽变量挂在 .tmb-card（Card 元素）上：工具条与书都是它的后代
   → 同宽居中，「请她写一篇」不再飞到屏幕最右缘与书脱节 */
.tmb-card { --tmb-col: 640px; }
.tmb-card .tm-journal-toolbar { max-width: var(--tmb-col); margin-inline: auto; }
/* 书脊列：布面 + 线装三孔 + 题签（竖排书名） */
.tmb-book-strip {
  position: relative; border-radius: 4px 0 0 4px;
  background-color: var(--tmb-cloth);
  /* 布面：左右一道圆柱高光 + 上下压暗（压暗吃 --tmb-cloth-lo，暗色块只改这一个变量） */
  background-image:
    linear-gradient(90deg, rgba(0, 0, 0, 0.42) 0%, rgba(255, 255, 255, 0.16) 38%, rgba(0, 0, 0, 0.22) 100%),
    linear-gradient(180deg, var(--tmb-cloth-lo) 0%, rgba(0, 0, 0, 0) 22%, rgba(0, 0, 0, 0) 78%, var(--tmb-cloth-lo) 100%),
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.07) 0 1px, rgba(0, 0, 0, 0.06) 1px 3px),
    repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.05) 0 1px, rgba(0, 0, 0, 0.05) 1px 2px);
  box-shadow: inset 0 0 0 1px rgba(255, 246, 226, 0.10), -1px 0 0 rgba(58, 42, 24, 0.18);
}
/* 线装孔：一条背景带上排三个圆点（33% 一格，repeat-y 出四个孔位，取中段三个的视觉） */
.tmb-book-stitch {
  position: absolute; left: 10px; top: 22px; bottom: 22px; width: 4px;
  background-image: radial-gradient(circle at 50% 50%, rgba(255, 251, 240, 0.92) 0 1.6px, rgba(40, 26, 12, 0.5) 1.6px 2.4px, transparent 2.4px);
  background-size: 4px 25%; background-repeat: repeat-y;
}
/* 题签：贴在书脊上的白纸条（古籍书签格式：框内竖排书名） */
.tmb-book-title {
  position: absolute; top: 26px; left: 5px; right: 6px; max-height: 112px; overflow: hidden;
  padding: 7px 1px; border-radius: 1px;
  writing-mode: vertical-rl; text-orientation: mixed;
  background: rgba(250, 244, 228, 0.94);
  box-shadow: inset 0 0 0 1px rgba(58, 42, 24, 0.22), 0 1px 3px rgba(28, 18, 8, 0.30);
  font-family: var(--tmb-kai); font-size: 10.5px; line-height: 1.2; letter-spacing: 0.06em;
  color: #43331d; text-align: center;
}
.tmb-book-strip--file {
  background-color: #56606e;
  background-image:
    linear-gradient(90deg, rgba(6, 12, 20, 0.46) 0%, rgba(255, 255, 255, 0.14) 40%, rgba(0, 0, 0, 0.26) 100%),
    repeating-linear-gradient(0deg, rgba(255, 255, 255, 0.06) 0 1px, rgba(0, 0, 0, 0.05) 1px 4px);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.10), -1px 0 0 rgba(14, 20, 28, 0.22);
}
/* 卷宗的装订：三个打孔（一条 12px 带上等距三孔）+ 一张贴在脊上的档案标签 */
.tmb-book-holes {
  position: absolute; left: 7px; top: 0; bottom: 0; width: 11px;
  background-image: radial-gradient(circle at 50% 50%, rgba(26, 34, 44, 0.62) 0 3.4px, rgba(255, 255, 255, 0.62) 3.4px 4.2px, transparent 4.2px);
  background-size: 11px 30%; background-repeat: repeat-y; background-position: 0 12%;
}
.tmb-book-title--file {
  top: 30px; left: 3px; right: 3px; max-height: 96px;
  background: rgba(244, 247, 251, 0.95); color: #2f3a47;
  box-shadow: inset 0 0 0 1px rgba(38, 46, 58, 0.24), 0 1px 3px rgba(14, 20, 28, 0.28);
  font-family: var(--tmb-song); font-size: 10px; letter-spacing: 0.1em;
}

/* ---- 纸页 ---- */
.tmb-page {
  /* flex 列 + 竖版下限：她只写两段时纸仍是一整页（空白落在页底、页脚钉在最下），
     而不是被内容拽成一条横幅——“扁”的主因（纸高曾完全由内容决定）。
     右内边距 62 = 丝带车道（丝带占纸页右缘 46~61px）：车道开在页上而不是页眉上，
     否则正文行尾仍会从丝带下面穿过去 */
  position: relative; display: flex; flex-direction: column;
  min-height: clamp(430px, 68vh, 700px);
  padding: 17px 62px 0 22px;
  border: 1px solid var(--tmb-paper-edge); border-left: none;
  border-radius: 0 6px 6px 0;
  background-color: var(--tmb-paper-mid);
  /* 四层：纤维 → 四边压暗（纸张厚度）→ 左上受光 → 基色渐变。
     透明度刻意拉到 .92~.96：既保住"摊在桌面上"的实体感，又不会把
     用户壁纸彻底糊死（面板外观那套 dim/blur 仍然吃得到） */
  background-image:
    repeating-linear-gradient(112deg, rgba(150, 124, 82, 0.052) 0 1px, transparent 1px 4px),
    repeating-linear-gradient(157deg, rgba(150, 124, 82, 0.04) 0 1px, transparent 1px 5px),
    radial-gradient(120% 100% at 50% 50%, rgba(255, 255, 255, 0) 58%, rgba(122, 96, 56, 0.14) 100%),
    radial-gradient(70% 55% at 10% 4%, rgba(255, 255, 255, 0.5), rgba(255, 255, 255, 0) 62%),
    linear-gradient(168deg, var(--tmb-paper-hi) 0%, var(--tmb-paper-mid) 52%, var(--tmb-paper-lo) 100%);
  box-shadow:
    inset 14px 0 16px -14px rgba(74, 54, 28, 0.42),
    inset -1px 0 0 rgba(255, 252, 242, 0.7),
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 9px 22px rgba(74, 54, 28, 0.15),
    0 2px 0 rgba(198, 178, 142, 0.5);
}
/* 版权页式页眉：一条界栏压底，字距拉开（和正文彻底分层） */
.tmb-head {
  display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap;
  padding: 0 12px 7px 0; margin-bottom: 11px;
  border-bottom: 1px solid var(--tmb-rule);
}
.tmb-head-kicker {
  font-family: var(--tmb-kai); font-size: 10.5px; letter-spacing: 0.26em;
  color: var(--tmb-ink-soft); text-transform: none;
}
.tmb-head-no { font-family: var(--tmb-print); font-size: 13.5px; font-weight: 700; color: var(--tmb-ink); letter-spacing: 0.02em; }
.tmb-head-meta { font-size: 11.5px; color: var(--tmb-ink-soft); font-variant-numeric: tabular-nums; }
.tmb-head-spacer { margin-left: auto; }
.tmb-head-trend { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--tmb-ink-soft); }
.tmb-head-trend .tm-mood-dot { width: 8px; height: 8px; box-shadow: 0 0 0 1px rgba(58, 42, 24, 0.18); }

/* 段落＝一张压在书里的纸：自己的边、自己的影、极轻微歪斜（手放的效果）。
   ⚠这里**不加** overflow:hidden：它是 .tmb-page 的直接子块，
   .tmb-page 才是 sticky 页脚的滚动上下文，别在这儿添堵 */
.tmb-entry {
  position: relative; margin-top: 14px; padding: 13px 12px 13px 14px;
  border: 1px solid rgba(198, 178, 142, 0.5);
  background-image:
    repeating-linear-gradient(104deg, rgba(150, 124, 82, 0.035) 0 1px, transparent 1px 4px),
    linear-gradient(172deg, rgba(255, 253, 246, 0.66) 0%, rgba(252, 247, 234, 0.4) 100%);
  box-shadow: 0 2px 5px rgba(74, 54, 28, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.7);
}
.tmb-entry:nth-child(even) { transform: rotate(-0.18deg); }
.tmb-entry:nth-child(odd) { transform: rotate(0.16deg); }
/* 四角贴角（和纸胶带）：左上 + 右下 */
.tmb-entry::before, .tmb-entry::after {
  content: ""; position: absolute; width: 11px; height: 26px;
  background: rgba(255, 252, 240, 0.5);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.6), 0 1px 2px rgba(74, 54, 28, 0.14);
}
.tmb-entry::before { left: -6px; top: 5px; transform: rotate(-34deg); }
.tmb-entry::after { right: -6px; bottom: 5px; transform: rotate(-34deg); }
.tmb-entry:first-child { margin-top: 0; }
/* 落笔时间：楷体小字，像她在页角写的日期 */
.tmb-entry-when {
  font-family: var(--tmb-kai); font-size: 10.5px; letter-spacing: 0.1em;
  color: var(--tmb-ink-soft); margin-bottom: 6px;
}
/* 分节小标题：界栏 + 字距拉开（"这段时间 / 我在想 / 对他的感觉 / 想说的"） */
.tmb-sec { margin-top: 11px; }
.tmb-sec:first-child { margin-top: 0; }
.tmb-sec-title {
  display: flex; align-items: center; gap: 8px; margin-bottom: 3px;
  font-family: var(--tmb-kai); font-size: 11px; letter-spacing: 0.2em;
  color: var(--tmb-ink-soft);
}
.tmb-sec-title::after { content: ""; flex: 1 1 auto; height: 1px; background: var(--tmb-rule); }
/* 正文：宣纸墨色 + 2.1 行距 + 中文惯例首行缩进；justify 拉齐右边像排过的 */
.tmb-text {
  margin: 0; font-size: 15px; line-height: 2.08;
  color: var(--tmb-ink); text-align: justify; text-indent: 2em;
  overflow-wrap: break-word; word-break: break-word;
}
.tmb-text + .tmb-text { margin-top: 7px; }
/* 首字下沉（全页只给第一段）：楷体大字，右上一个「」起首 */
.tmb-text--lead { text-indent: 0; }
.tmb-text--lead::first-letter {
  float: left; padding: 3px 7px 0 0;
  font-family: var(--tmb-kai); font-size: 2.15em; line-height: 1.02;
  color: rgba(94, 66, 34, 0.92);
}

/* 丝带书签：压在页脚之上、被页脚遮住下半（真丝带的层叠关系）。
   页很高时百分比会拉成一条桌旗，故上下限夹住：短页 96px、长页最多 420px */
.tmb-ribbon {
  position: absolute; top: 0; right: 46px; width: 15px; height: 56%;
  min-height: 96px; max-height: 420px;
  background-color: var(--tmb-ribbon);
  background-image:
    linear-gradient(90deg, rgba(0, 0, 0, 0.26) 0%, rgba(255, 255, 255, 0.24) 38%, rgba(0, 0, 0, 0.18) 100%),
    repeating-linear-gradient(90deg, rgba(255, 255, 255, 0.10) 0 1px, rgba(0, 0, 0, 0.06) 1px 3px);
  clip-path: polygon(0 0, 100% 0, 100% 100%, 50% 88%, 0 100%);
  z-index: 2; pointer-events: none;
}
/* 封面内衬的合页阴影：靠近书脊那一侧压一道 */
.tmb-page-body { position: relative; flex: 1 1 auto; min-height: 0; }
.tmb-page-body::before {
  content: ""; position: absolute; left: -18px; top: 0; bottom: 0; width: 18px;
  background: linear-gradient(90deg, rgba(58, 42, 24, 0.0), rgba(58, 42, 24, 0.12));
  pointer-events: none;
}

/* 页脚：常驻下缘（连续卷轴 + 分页视觉的落点）——实色底 + 上界栏 + 模糊，
   不画圆角（页脚即页面的收口），见文件头约束 3 */
.tmb-foot {
  position: sticky; bottom: 0; z-index: 4;
  /* 页脚左右顶到纸边（含丝带车道），但不向下顶：纸页已是 flex 列且 padding-bottom=0，
     再给负 bottom 会在页脚下面留一条纸底白缝 */
  margin: 14px -62px 0 -22px; padding: 9px 18px 11px;
  display: flex; align-items: center; gap: 10px;
  background-image: linear-gradient(180deg, rgba(246, 239, 224, 0.96) 0%, rgba(240, 231, 212, 0.99) 100%);
  border-top: 1px solid rgba(198, 178, 142, 0.72);
  /* 页脚负外边距顶到纸边，右下角跟随纸页圆角（否则直角会在圆纸上露一尖） */
  border-radius: 0 0 6px 0;
  box-shadow: 0 -5px 12px rgba(74, 54, 28, 0.13), inset 0 1px 0 rgba(255, 255, 255, 0.8);
  -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px);
}
.tmb-foot-mid { margin-left: auto; display: flex; align-items: center; gap: 12px; }
.tmb-btn {
  border: 1px solid rgba(120, 96, 58, 0.44); border-radius: 999px;
  padding: 5px 13px; background: rgba(253, 250, 242, 0.86);
  color: #4a3a22; font: inherit; font-size: 12.5px; letter-spacing: 0.04em;
  cursor: pointer;
  transition: background 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}
.tmb-btn:hover:not(:disabled) { background: rgba(255, 253, 248, 0.98); box-shadow: 0 2px 7px rgba(74, 54, 28, 0.18); transform: translateY(-1px); }
.tmb-btn:active:not(:disabled) { transform: translateY(0); }
.tmb-btn:disabled { opacity: 0.4; cursor: default; }
.tmb-btn:focus-visible { outline: 2px solid rgba(200, 150, 90, 0.85); outline-offset: 2px; }
.tmb-ind {
  min-width: 54px; text-align: center; font-size: 12.5px; letter-spacing: 0.06em;
  color: rgba(74, 58, 32, 0.9); font-variant-numeric: tabular-nums;
  font-family: var(--tmb-print);
}
.tmb-leaf-ind { font-size: 11px; color: rgba(120, 102, 68, 0.86); font-variant-numeric: tabular-nums; }

/* ============================================================
   3. 铅印卷宗（我的日记专属）：冷纸 + 仿宋正文 + 等宽口径 + 朱印
   ============================================================ */
.tmb-page--file {
  border-color: var(--tmb-file-edge);
  background-color: var(--tmb-file-paper-lo);
  /* 打字纸：极淡横格（21px 一格，与 1.9 行距对不上就不对，反正淡）+ 冷色基渐变 */
  background-image:
    repeating-linear-gradient(0deg, rgba(72, 86, 104, 0.055) 0 1px, transparent 1px 21px),
    radial-gradient(120% 100% at 50% 50%, rgba(255, 255, 255, 0) 62%, rgba(46, 58, 72, 0.12) 100%),
    radial-gradient(66% 50% at 8% 2%, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0) 60%),
    linear-gradient(168deg, var(--tmb-file-paper-hi) 0%, #eef1f5 54%, var(--tmb-file-paper-lo) 100%);
  box-shadow:
    inset 16px 0 18px -16px rgba(14, 20, 28, 0.4),
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    0 9px 20px rgba(18, 26, 36, 0.14),
    0 2px 0 rgba(120, 132, 150, 0.42);
}
.tmb-page--file .tmb-head { border-bottom-color: var(--tmb-file-rule); }
.tmb-page--file .tmb-head-kicker { font-family: var(--tmb-song); letter-spacing: 0.3em; color: rgba(52, 64, 78, 0.9); }
.tmb-page--file .tmb-head-no { font-family: var(--tmb-mono); font-weight: 600; color: #26313d; }
.tmb-page--file .tmb-head-meta { color: rgba(52, 64, 78, 0.9); }
.tmb-page--file .tmb-head-trend { color: rgba(52, 64, 78, 0.9); }
/* 卷首统计口径：等宽小字 + 上下细线（档案表格的味道），纯数据无修饰 */
.tmb-dossier {
  display: flex; flex-wrap: wrap; gap: 4px 16px; align-items: baseline;
  padding: 7px 9px; margin-bottom: 12px;
  border-top: 1.5px solid rgba(46, 58, 72, 0.55); border-bottom: 1px solid var(--tmb-file-rule);
  background: rgba(255, 255, 255, 0.34);
}
.tmb-dossier-item {
  display: inline-flex; align-items: baseline; gap: 5px;
  font-family: var(--tmb-mono); font-size: 10.5px; letter-spacing: 0.01em; color: #33404e;
}
.tmb-dossier-label { opacity: 0.66; }
.tmb-dossier-value { font-weight: 700; color: #1f2a35; }
/* 标题居中一行（"这一段时间的记录"）：宋体宽字距，铅字标题 */
.tmb-file-title {
  margin: 2px 0 12px; text-align: center;
  font-family: var(--tmb-song); font-size: 13px; font-weight: 700; letter-spacing: 0.34em;
  color: #26313d;
}
/* 正文：仿宋 + 铅字压痕（1px 白影 = 油墨吃进纸纤维） */
.tmb-text--file {
  font-family: var(--tmb-song); font-size: 14px; line-height: 1.95; color: var(--tmb-file-ink);
  text-shadow: 0 1px 0 rgba(255, 255, 255, 0.72);
}
.tmb-page--file .tmb-entry {
  border-color: rgba(120, 132, 150, 0.34);
  background-image:
    repeating-linear-gradient(96deg, rgba(72, 86, 104, 0.03) 0 1px, transparent 1px 4px),
    linear-gradient(172deg, rgba(255, 255, 255, 0.6) 0%, rgba(246, 248, 251, 0.42) 100%);
  box-shadow: 0 2px 5px rgba(18, 26, 36, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.86);
}
.tmb-page--file .tmb-entry::before, .tmb-page--file .tmb-entry::after { background: rgba(244, 247, 251, 0.62); box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.7), 0 1px 2px rgba(18, 26, 36, 0.14); }
.tmb-page--file .tmb-entry:nth-child(even), .tmb-page--file .tmb-entry:nth-child(odd) { transform: none; }
/* 卷宗不贴角、不歪斜：那是她手边的东西，档案是打好的 */
/* 落款朱印：方框双线 + 楷体竖排 + 轻旋转（盖章必不正），流在正文之后靠右。
   单列装不下时竖排自动往左换第二列——正好是印章的多列排字，故不裁剪；
   颜色走 --tmb-seal（暗色块只改这一个变量） */
.tmb-seal {
  float: right; clear: both; margin: 16px 2px 0 18px;
  width: 46px; height: 62px; padding: 6px 0;
  display: flex; align-items: center; justify-content: center;
  border: 2px solid var(--tmb-seal); border-radius: 3px;
  color: var(--tmb-seal);
  background-image: radial-gradient(circle at 32% 28%, rgba(255, 255, 255, 0.5), rgba(255, 255, 255, 0) 62%);
  box-shadow: inset 0 0 0 1px var(--tmb-seal);
  writing-mode: vertical-rl; text-orientation: upright;
  font-family: var(--tmb-kai); font-size: 11.5px; letter-spacing: 0.04em; line-height: 1.05;
  transform: rotate(-5.5deg);
}
.tmb-page--file .tmb-foot {
  background-image: linear-gradient(180deg, rgba(238, 241, 245, 0.96) 0%, rgba(230, 234, 240, 0.99) 100%);
  border-top-color: rgba(120, 132, 150, 0.6);
  box-shadow: 0 -5px 12px rgba(18, 26, 36, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.tmb-page--file .tmb-btn { border-color: rgba(52, 64, 78, 0.4); background: rgba(250, 251, 253, 0.9); color: #2f3a46; }
.tmb-page--file .tmb-btn:hover:not(:disabled) { background: #fff; box-shadow: 0 2px 7px rgba(18, 26, 36, 0.18); }
.tmb-page--file .tmb-ind, .tmb-page--file .tmb-leaf-ind { font-family: var(--tmb-mono); color: rgba(46, 58, 72, 0.92); }
/* 素材进度（卷宗式：等宽计数 + 一根实心条，不用面板那根渐变色条） */
.tmb-meter { display: grid; gap: 5px; margin: 0 0 12px; }
.tmb-meter-row { display: flex; align-items: baseline; gap: 8px; font-family: var(--tmb-mono); font-size: 10.5px; color: rgba(52, 64, 78, 0.92); letter-spacing: 0.01em; }
.tmb-meter-track { height: 5px; border-radius: 1px; background: rgba(72, 86, 104, 0.18); box-shadow: inset 0 1px 1px rgba(18, 26, 36, 0.18); overflow: hidden; }
.tmb-meter-fill { height: 100%; background: linear-gradient(90deg, rgba(94, 108, 126, 0.85), rgba(58, 72, 90, 0.9)); }

/* 藏书阁（1.3.0）：书架末尾横叠的一小摞——写满下架的旧页都在这儿，只读翻阅。
   不标本数、不提 52 上限（显示层纪律：不在活架上加计数）；布面取书脊同族
   色系但压暗两档——收起来的旧时光不该比活页抢眼；三块板微错位堆叠，
   坐在同一根木隔板上（.tmb-shelf 的 align-items: flex-end 负责兑底） */
.tmb-stack {
  position: relative; flex: 0 0 auto;
  width: 58px; height: 46px; margin-left: 16px;
  border: 0; padding: 0; background: none; cursor: pointer;
}
.tmb-stack-slab {
  position: absolute; left: 2px; right: 2px; bottom: 0;
  height: 13px; border-radius: 2px 3px 3px 2px;
  background: linear-gradient(180deg, rgba(107, 79, 54, 0.92) 0%, rgba(74, 53, 36, 0.95) 62%, rgba(56, 39, 25, 0.96) 100%);
  border: 1px solid rgba(58, 42, 24, 0.44);
  box-shadow: 0 2px 5px rgba(70, 50, 28, 0.26), inset 0 1px 0 rgba(255, 246, 226, 0.12);
}
.tmb-stack-slab--back { left: 6px; right: -2px; transform: rotate(-0.7deg); }
.tmb-stack-slab--mid { bottom: 11px; left: 3px; right: 5px; transform: rotate(0.5deg); }
.tmb-stack-slab--top {
  bottom: 22px; left: 4px; right: 3px;
  transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.tmb-stack:hover .tmb-stack-slab--top { transform: translateY(-3px) rotate(-0.8deg); box-shadow: 0 5px 10px rgba(70, 50, 28, 0.34), inset 0 1px 0 rgba(255, 246, 226, 0.16); }
/* 切口一侧的纸口线：三板各画一道，读出“这里是一探书，不是一块砖” */
.tmb-stack-slab::before {
  content: ""; position: absolute; left: 3px; right: 3px; top: 50%;
  height: 3px; border-radius: 1px;
  background: linear-gradient(180deg, rgba(248, 242, 227, 0.85), rgba(228, 216, 190, 0.7));
  box-shadow: inset 0 0 0 1px rgba(120, 102, 68, 0.18);
}
/* 封面题签：一枚朱色小印，里面一个“藏”字（盖章位子在书摞右上角） */
.tmb-stack-seal {
  position: absolute; right: 5px; top: -3px; z-index: 2;
  width: 16px; height: 16px; border-radius: 3px;
  display: flex; align-items: center; justify-content: center;
  background: var(--tmb-seal);
  color: #f6efe0; font-size: 10px; line-height: 1;
  font-family: var(--tmb-kai);
  box-shadow: 0 1px 3px rgba(40, 20, 10, 0.4), inset 0 0 0 1px rgba(255, 246, 226, 0.22);
  transform: rotate(-4deg);
}
/* 丝带从书摞里探出来，搭在隔板沿上 */
.tmb-stack-ribbon {
  position: absolute; left: 10px; top: 10px; z-index: 1;
  width: 7px; height: 20px;
  background: linear-gradient(180deg, var(--tmb-ribbon), rgba(120, 40, 34, 0.9));
  clip-path: polygon(0 0, 100% 0, 100% 100%, 50% 78%, 0 100%);
  box-shadow: 0 1px 2px rgba(40, 20, 10, 0.35);
}

/* ============================================================
   4. 暗色孪生：一间屋子里的一盏灯——手写本偏暖褐，卷宗偏冷灰
   ============================================================ */
@media (prefers-color-scheme: dark) {
  .tmb-book, .tmb-shelf {
    --tmb-paper-hi: #2e2719;
    --tmb-paper-mid: #271f14;
    --tmb-paper-lo: #201910;
    --tmb-paper-edge: rgba(168, 146, 108, 0.34);
    --tmb-ink: #e6dcc4;
    --tmb-ink-soft: rgba(198, 178, 142, 0.9);
    --tmb-rule: rgba(168, 146, 108, 0.28);
    --tmb-cloth: #3b2c1e;
    --tmb-cloth-lo: #241a11;
    --tmb-ribbon: #7d2f29;
    --tmb-file-paper-hi: #212836;
    --tmb-file-paper-lo: #161c26;
    --tmb-file-edge: rgba(148, 164, 184, 0.26);
    --tmb-file-ink: #ccd6e2;
    --tmb-file-rule: rgba(148, 164, 184, 0.24);
    --tmb-seal: rgba(214, 96, 74, 0.86);
  }
  .tmb-shelf::after {
    background: linear-gradient(180deg, rgba(112, 84, 50, 0.5) 0%, rgba(70, 52, 32, 0.42) 55%, rgba(30, 22, 12, 0.34) 100%);
    box-shadow: 0 4px 10px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(198, 178, 142, 0.18);
  }
  .tmb-spine { border-color: rgba(14, 10, 4, 0.5); box-shadow: 2px 4px 10px rgba(0, 0, 0, 0.45), inset -3px 0 6px rgba(0, 0, 0, 0.4), inset 3px 0 5px rgba(255, 246, 226, 0.10); }
  .tmb-spine:hover { box-shadow: 2px 14px 20px rgba(0, 0, 0, 0.5), inset -3px 0 6px rgba(0, 0, 0, 0.4), inset 3px 0 5px rgba(255, 246, 226, 0.14); }
  .tmb-spine-top { background: linear-gradient(180deg, rgba(96, 84, 64, 0.95), rgba(60, 52, 38, 0.85)); box-shadow: 0 1px 0 rgba(0, 0, 0, 0.4); }
  .tmb-spine-no { background: rgba(64, 54, 38, 0.9); color: #ecdcb8; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.36); }
  .tmb-spine--file { background-color: #46505e; border-color: rgba(4, 8, 14, 0.55); }
  .tmb-spine--file .tmb-spine-top { background: linear-gradient(180deg, rgba(84, 96, 112, 0.95), rgba(50, 60, 74, 0.85)); }
  .tmb-spine--file .tmb-spine-no { background: rgba(40, 50, 62, 0.92); color: #d9e4f0; }
  .tmb-book-title { background: rgba(62, 52, 34, 0.92); color: #ead9b6; box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.34), 0 1px 3px rgba(0, 0, 0, 0.4); }
  .tmb-book-title--file { background: rgba(38, 48, 60, 0.94); color: #cfdbe8; }
  .tmb-page { box-shadow: inset 14px 0 16px -14px rgba(0, 0, 0, 0.6), inset -1px 0 0 rgba(255, 246, 226, 0.06), inset 0 1px 0 rgba(255, 246, 226, 0.08), 0 9px 24px rgba(0, 0, 0, 0.45), 0 2px 0 rgba(0, 0, 0, 0.3); }
  .tmb-page--file { box-shadow: inset 16px 0 18px -16px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 9px 22px rgba(0, 0, 0, 0.44), 0 2px 0 rgba(0, 0, 0, 0.3); }
  .tmb-entry { border-color: rgba(168, 146, 108, 0.24); box-shadow: 0 2px 6px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 246, 226, 0.05); }
  .tmb-entry::before, .tmb-entry::after { background: rgba(198, 178, 142, 0.16); box-shadow: inset 0 0 0 1px rgba(255, 246, 226, 0.1), 0 1px 2px rgba(0, 0, 0, 0.3); }
  .tmb-page--file .tmb-entry { border-color: rgba(148, 164, 184, 0.18); }
  .tmb-page--file .tmb-dossier { border-top-color: rgba(148, 164, 184, 0.4); border-bottom-color: rgba(148, 164, 184, 0.22); background: rgba(0, 0, 0, 0.2); }
  .tmb-dossier-item, .tmb-page--file .tmb-head-kicker, .tmb-page--file .tmb-head-meta, .tmb-page--file .tmb-head-trend { color: #c3cfdd; }
  .tmb-dossier-value, .tmb-file-title, .tmb-page--file .tmb-head-no { color: #e6edf5; }
  .tmb-text--file { color: #ccd6e2; text-shadow: 0 1px 0 rgba(0, 0, 0, 0.45); }
  .tmb-seal { background-image: radial-gradient(circle at 32% 28%, rgba(255, 255, 255, 0.12), rgba(255, 255, 255, 0) 62%); }
  .tmb-foot { background-image: linear-gradient(180deg, rgba(44, 36, 24, 0.96) 0%, rgba(34, 28, 18, 0.99) 100%); border-top-color: rgba(168, 146, 108, 0.32); box-shadow: 0 -5px 14px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 246, 226, 0.06); }
  .tmb-btn { border-color: rgba(198, 178, 142, 0.32); background: rgba(58, 48, 32, 0.86); color: #e6dcc4; }
  .tmb-btn:hover:not(:disabled) { background: rgba(76, 62, 42, 0.95); box-shadow: 0 2px 8px rgba(0, 0, 0, 0.42); }
  .tmb-ind, .tmb-leaf-ind { color: rgba(214, 198, 166, 0.92); }
  .tmb-page--file .tmb-foot { background-image: linear-gradient(180deg, rgba(30, 37, 49, 0.96) 0%, rgba(22, 28, 38, 0.99) 100%); border-top-color: rgba(148, 164, 184, 0.24); }
  .tmb-page--file .tmb-btn { border-color: rgba(148, 164, 184, 0.26); background: rgba(36, 45, 58, 0.9); color: #d3dde8; }
  .tmb-page--file .tmb-btn:hover:not(:disabled) { background: rgba(48, 60, 76, 0.96); }
  .tmb-page--file .tmb-ind, .tmb-page--file .tmb-leaf-ind { color: rgba(205, 216, 228, 0.92); }
  .tmb-meter-track { background: rgba(148, 164, 184, 0.2); box-shadow: inset 0 1px 1px rgba(0, 0, 0, 0.4); }
  .tmb-meter-fill { background: linear-gradient(90deg, rgba(150, 168, 190, 0.9), rgba(110, 128, 152, 0.95)); }
  .tmb-meter-row { color: rgba(195, 207, 221, 0.95); }
  .tmb-text--lead::first-letter { color: rgba(214, 184, 128, 0.95); }
  .tmb-page-body::before { background: linear-gradient(90deg, rgba(0, 0, 0, 0), rgba(0, 0, 0, 0.34)); }
  .tmb-stack-slab { background: linear-gradient(180deg, rgba(76, 56, 38, 0.95) 0%, rgba(52, 37, 24, 0.96) 62%, rgba(36, 25, 15, 0.98) 100%); border-color: rgba(14, 10, 4, 0.55); box-shadow: 0 2px 6px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255, 246, 226, 0.08); }
  .tmb-stack-slab::before { background: linear-gradient(180deg, rgba(214, 198, 166, 0.5), rgba(180, 164, 134, 0.4)); box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.3); }
  .tmb-stack-seal { color: #f2e8d5; }
}

/* ============================================================
   5. 小窗降级（1.2.9 之后的同一条纪律：不留"看得见但点不到"的东西）
   窗口很窄时书脊列与斜角贴纸先让路，正文优先吃宽度
   ============================================================ */
@media (max-width: 460px) {
  .tmb-book { grid-template-columns: 19px minmax(0, 1fr); }
  .tmb-book-stitch, .tmb-book-holes { display: none; }
  .tmb-book-title { left: 2px; right: 2px; font-size: 9.5px; }
  .tmb-page { padding: 14px 40px 0 15px; min-height: clamp(360px, 62vh, 620px); }
  .tmb-entry { padding: 11px 9px 11px 10px; }
  .tmb-entry::before, .tmb-entry::after { display: none; }
  .tmb-entry:nth-child(even), .tmb-entry:nth-child(odd) { transform: none; }
  .tmb-text { font-size: 14px; line-height: 2.02; }
  .tmb-foot { margin: 12px -40px 0 -15px; padding: 8px 12px 10px; }
  /* 小窗车道收窄（丝带右 24 + 宽 12 → 占 24~36），页右内边距 40 已足避让 */
  .tmb-card { --tmb-col: 100%; }
  .tmb-btn { padding: 5px 10px; font-size: 12px; }
  .tmb-ribbon { right: 24px; width: 12px; }
}

/* 动效关闭偏好：书本不弹、纸叠不歪 */
@media (prefers-reduced-motion: reduce) {
  .tmb-spine, .tmb-spine:hover, .tmb-btn, .tmb-btn:hover:not(:disabled) { transform: none !important; transition: none !important; }
  .tmb-entry:nth-child(even), .tmb-entry:nth-child(odd) { transform: none !important; }
  .tmb-stack-slab, .tmb-stack-slab--top, .tmb-stack:hover .tmb-stack-slab--top { transform: none !important; transition: none !important; }
}
`
