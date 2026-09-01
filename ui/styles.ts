// 面板样式（安静版磨砂）：静态淡蓝白弥散底，无环境动效；动效只保留交互反馈与今日标记呼吸
export const PANEL_STYLES = `
.neko-page {
  height: 100vh; padding: 0; gap: 0; display: flex; flex-direction: column; overflow: hidden;
  position: relative; z-index: 0;
  background:
    radial-gradient(900px 460px at 88% -10%, rgba(147, 197, 253, 0.10), transparent 60%),
    radial-gradient(800px 420px at -8% 108%, rgba(196, 181, 253, 0.07), transparent 58%),
    linear-gradient(160deg, #f8fbff 0%, #fbfcff 50%, #f3f7fd 100%);
}

.neko-card, .tm-card {
  border: 1px solid rgba(255, 255, 255, 0.85);
  border-radius: var(--radius-lg);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.72) 0%, rgba(255, 255, 255, 0.56) 100%);
  -webkit-backdrop-filter: blur(12px) saturate(1.3);
  backdrop-filter: blur(12px) saturate(1.3);
  box-shadow: 0 1px 2px rgba(96, 165, 250, 0.06), 0 10px 30px rgba(96, 165, 250, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.neko-input, .neko-select, .neko-textarea { background: rgba(255, 255, 255, 0.7); }
.neko-button {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.78) 0%, rgba(255, 255, 255, 0.55) 100%);
  border-color: rgba(255, 255, 255, 0.9);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
  box-shadow: 0 1px 2px rgba(96, 165, 250, 0.08), 0 4px 12px rgba(96, 165, 250, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.95);
}
.neko-button:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(255, 255, 255, 0.68) 100%);
  box-shadow: 0 2px 4px rgba(96, 165, 250, 0.10), 0 8px 20px rgba(96, 165, 250, 0.18), inset 0 1px 0 rgba(255, 255, 255, 1);
}
.neko-button[data-tone="primary"] {
  background: linear-gradient(180deg, rgba(64, 158, 255, 0.24) 0%, rgba(64, 158, 255, 0.13) 100%);
  border-color: rgba(64, 158, 255, 0.42);
  box-shadow: 0 1px 2px rgba(64, 158, 255, 0.10), 0 6px 16px rgba(64, 158, 255, 0.20), inset 0 1px 0 rgba(255, 255, 255, 0.6);
}
.neko-button[data-tone="primary"]:hover:not(:disabled) {
  background: linear-gradient(180deg, rgba(64, 158, 255, 0.32) 0%, rgba(64, 158, 255, 0.18) 100%);
  box-shadow: 0 2px 4px rgba(64, 158, 255, 0.12), 0 8px 20px rgba(64, 158, 255, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.7);
}
.neko-button[data-tone="danger"] { box-shadow: 0 1px 2px rgba(245, 108, 108, 0.08), 0 4px 12px rgba(245, 108, 108, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.7); }
.neko-button[data-tone="success"] { box-shadow: 0 1px 2px rgba(103, 194, 58, 0.08), 0 4px 12px rgba(103, 194, 58, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.7); }
.neko-button:active:not(:disabled) { transform: translateY(0) scale(0.97); }
/* 宿主 kit 对禁用按钮用了 cursor: wait（Windows 上显示转圈忙碌光标），这里纠正为不可点击 */
.neko-page .neko-button:disabled { cursor: not-allowed; }

/* ---- Tooltip 修复（宿主 kit 缺陷，仅本面板内覆盖）----
   宿主 .neko-tooltip-content 是挂在被悬停元素（往往只有 50px 宽的徽章格/热力格）里的
   absolute 元素：没写宽度下限，shrink-to-fit 的可用宽被包含块（那个小格子）压窄，
   一句话被折成 44px 宽的竖条（一字一行）。修复：
   1) width: max-content —— 先按内容自然宽；
   2) max-width: min(280px, 80vw) —— 超长文到上限才优雅折行（自适应换行）；
   3) 边缘翻转：靠近面板左缘时以左缘为锚向右展开、右缘同理向左——
      用 :has() 容器查询近似"贴边"判定不可靠（沙箱运行时对 :has 支持未验证），
      改用更稳的做法：父级 .neko-tooltip 若是行内首/尾元素，用 text-align 感知不现实，
      故采用 grid 隐式列 + 匿名盒定位——最终方案见下方实现注释。 */
.neko-page .neko-tooltip-content {
  width: max-content;
  max-width: min(280px, 80vw);
  white-space: normal;
}

.tm-statusbar {
  display: flex; align-items: center; gap: 18px; flex-wrap: wrap;
  padding: 14px 22px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.68) 0%, rgba(255, 255, 255, 0.5) 100%);
  -webkit-backdrop-filter: blur(12px) saturate(1.3);
  backdrop-filter: blur(12px) saturate(1.3);
  border-bottom: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 6px 20px rgba(96, 165, 250, 0.10), inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

.tm-ring-wrap {
  position: relative; width: 80px; height: 80px; flex: 0 0 auto;
  cursor: pointer; user-select: none;
  transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tm-ring-wrap:hover { transform: scale(1.06); }
.tm-ring-wrap:active { transform: scale(0.96); }
.tm-ring-glow {
  position: absolute; inset: -16%; border-radius: 999px; pointer-events: none;
  background: radial-gradient(closest-side, rgba(246, 239, 221, 0.55), rgba(246, 239, 221, 0) 72%);
  filter: blur(8px);
  transition: filter 0.25s ease, opacity 0.6s ease;
}
.tm-ring-wrap:hover .tm-ring-glow { filter: blur(8px) brightness(1.15); }
.tm-ring-track {
  position: absolute; inset: 0; border-radius: 999px; overflow: hidden;
  -webkit-mask: radial-gradient(farthest-side, transparent 61%, #000 62%);
  mask: radial-gradient(farthest-side, transparent 61%, #000 62%);
}
.tm-ring-surge-sweep {
  position: absolute; inset: -25%;
  background: conic-gradient(from 0deg, rgba(255, 255, 255, 0) 0deg, rgba(255, 255, 255, 0.9) 45deg, rgba(255, 255, 255, 0) 100deg);
  animation: tm-ring-surge 0.85s cubic-bezier(0.3, 0.6, 0.35, 1) both;
}
/* 外圈细轨道：中性发丝环，阶段分布由边界小点表达 */
.tm-ring-orbit {
  position: absolute; inset: 0; z-index: 2; border-radius: 999px; pointer-events: none;
  border: 2px solid rgba(100, 116, 139, 0.20);
}
.tm-ring-phase-dot {
  position: absolute; left: 50%; top: 50%; z-index: 2; pointer-events: none;
  width: 5px; height: 5px; margin-left: -2.5px; margin-top: -2.5px; border-radius: 999px;
  border: 1px solid rgba(255, 255, 255, 0.9);
}
.tm-ring-marker {
  position: absolute; z-index: 3; width: 12px; height: 12px; border-radius: 999px;
  background: var(--text); border: 2.5px solid rgba(255, 255, 255, 0.95);
  transform: translate(-50%, -50%);
  transition: transform 0.2s ease;
  animation: tm-breathe 2.4s ease-in-out infinite;
}
.tm-ring-wrap:hover .tm-ring-marker { transform: translate(-50%, -50%) scale(1.18); }

/* 中心月相盘：玻璃暗面 + 整面亮盘 + 同尺寸暗盘横向扫过（translateX 驱动盈亏）。
   原则：暗面=与面板融合的玻璃（新月≈隐身），只有亮部是实体；扫掠暗盘与暗面同材质，
   暗盘必须是实体遮盖（不透明渐变）--曾用 backdrop-filter 压暗下方亮盘，但面板运行环境
   里该滤镜不生效：暗盘只剩自身 10~15% 透明渐变，该遮住的区域整个透出亮盘纹理（穿模），
   已改为实体暗玻璃。无球面罩层--发光体要 bloom 不要灰。 */
.tm-moon {
  position: absolute; inset: 15%; z-index: 3; border-radius: 999px; overflow: hidden;
}
.tm-moon-base {
  position: absolute; inset: 0; border-radius: 999px;
  background: radial-gradient(circle at 36% 32%, rgba(148, 163, 184, 0.10), rgba(100, 116, 139, 0.15) 80%);
  -webkit-backdrop-filter: blur(3px);
  backdrop-filter: blur(3px);
  /* 新月轮廓光：右缘一线极淡亮边，让暗盘在月初也有月亮轮廓 */
  box-shadow: inset -1.5px 0 2px rgba(246, 239, 221, 0.22), inset 0 0 0 1px rgba(100, 116, 139, 0.12);
}
.tm-moon-lit {
  position: absolute; inset: 0; border-radius: 999px;
  background:
    radial-gradient(circle 7px at 63% 36%, rgba(168, 152, 118, 0.15), transparent 72%),
    radial-gradient(circle 5px at 41% 58%, rgba(168, 152, 118, 0.11), transparent 72%),
    radial-gradient(circle at 38% 32%, #fffef9, #f5edda 65%, #e9ddc2 100%);
  /* 内发光：让亮部像光源而不是纸片 */
  box-shadow: inset 0 0 12px rgba(255, 252, 240, 0.75);
}
/* 扫掠暗盘：与暗面同材质的实体暗玻璃（不透明），横向扫过遮住亮盘；边缘 0.5px 羽化。
   禁止改回半透明+backdrop-filter--面板环境该滤镜不生效，暗区会整个透出亮盘（穿模） */
.tm-moon-shadow {
  position: absolute; inset: 0; border-radius: 999px;
  background: radial-gradient(circle at 36% 32%, #ccd5e2, #b3bfd2 80%);
  box-shadow: inset 0 0 0 1px rgba(100, 116, 139, 0.12);
  filter: blur(0.5px);
}
/* 月相盘中心的信息 pill：三视图文本 */
.tm-moon-pill {
  position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
  z-index: 4; max-width: 92%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  padding: 1px 7px; border-radius: 999px; font-size: 10px; font-weight: 700; line-height: 1.5;
  color: var(--text);
  background: rgba(255, 255, 255, 0.72);
  -webkit-backdrop-filter: blur(6px);
  backdrop-filter: blur(6px);
  box-shadow: 0 1px 5px rgba(2, 6, 23, 0.16);
  pointer-events: none;
  animation: tm-center-pop 0.32s cubic-bezier(0.34, 1.56, 0.64, 1) both;
}

/* 圆环三视图指示点：让"点击切换"可发现，点本身也可直接点按切换 */
.tm-ring-col { display: flex; flex-direction: column; align-items: center; gap: 6px; flex: 0 0 auto; }
.tm-ring-dots { display: flex; gap: 5px; }
.tm-ring-dot {
  width: 6px; height: 6px; border-radius: 999px; border: none; padding: 0; cursor: pointer;
  background: rgba(100, 116, 139, 0.28);
  transition: background 0.18s ease, transform 0.18s ease;
}
.tm-ring-dot:hover { background: rgba(100, 116, 139, 0.5); }
.tm-ring-dot-active { background: var(--primary); transform: scale(1.25); }

.tm-status-text { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1 1 180px; }
.tm-phase-label { font-size: 19px; font-weight: 800; line-height: 1.25; }
.tm-status-sub { color: var(--muted); font-size: 12.5px; line-height: 1.5; }
.tm-status-right { display: flex; align-items: center; gap: 10px; margin-left: auto; }

/* ---- 精简状态条（0.9.0）：她是谁 · 一句话状态 · 心情胶囊 · 开关 ---- */
.tm-statusbar-slim { padding: 10px 22px; gap: 12px; }
.tm-status-main {
  display: inline-flex; align-items: center; gap: 10px; min-width: 0;
  padding: 4px 10px 4px 6px; border: none; border-radius: 999px; cursor: pointer;
  background: transparent; color: var(--text); text-align: left;
  transition: background 0.15s ease;
}
.tm-status-main:hover { background: rgba(148, 163, 184, 0.12); }
.tm-status-dot { width: 9px; height: 9px; border-radius: 999px; flex: 0 0 auto; box-shadow: 0 0 6px rgba(255, 255, 255, 0.6); }
.tm-status-name { font-size: 14px; font-weight: 750; white-space: nowrap; }
.tm-status-summary { font-size: 13px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tm-statusbar-slim .tm-status-main:hover .tm-status-summary { color: var(--text); }

/* ---- 总览页（0.9.0）：陪伴仪表盘 ---- */
.tm-ov-hero { display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }
.tm-ov-hero-text { display: flex; flex-direction: column; gap: 4px; min-width: 160px; flex: 1 1 200px; }
.tm-ov-name { font-size: 16px; font-weight: 800; opacity: 0.85; }
.tm-ov-mood-chip { display: inline-flex; align-items: center; gap: 10px; margin-top: 4px; flex-wrap: wrap; }
.tm-ov-mood { display: flex; align-items: center; gap: 18px; flex-wrap: wrap; }
.tm-ov-mood-word { font-size: 26px; font-weight: 800; line-height: 1.2; min-width: 72px; }
.tm-ov-mood-bars { display: grid; gap: 10px; flex: 1 1 220px; }
.tm-ov-minibar { display: grid; grid-template-columns: 52px 1fr 34px; align-items: center; gap: 10px; }
.tm-ov-minibar-label { color: var(--muted); font-size: 12px; }
.tm-ov-minibar-value { color: var(--muted); font-size: 12px; text-align: right; }
.tm-ov-minibar-track {
  position: relative; height: 8px; border-radius: 999px; overflow: hidden;
  background: rgba(148, 163, 184, 0.22);
}
.tm-ov-minibar-fill { position: absolute; top: 0; bottom: 0; border-radius: 999px; transition: left 0.3s ease, width 0.3s ease; }
/* 双向条的中心零点刻度：愉悦度左负右正，静息态时填充缩成一个点也不失语义 */
.tm-ov-minibar-zero {
  position: absolute; left: 50%; top: 0; bottom: 0; z-index: 1;
  width: 1.5px; margin-left: -0.75px;
  background: rgba(100, 116, 139, 0.55);
}
.tm-ov-minibar-fill { z-index: 2; }
.tm-ov-diary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.tm-ov-tile {
  display: flex; flex-direction: column; align-items: flex-start; gap: 3px;
  padding: 12px 14px; border-radius: var(--radius-md); cursor: pointer; text-align: left;
  border: 1px solid rgba(255, 255, 255, 0.7); background: rgba(255, 255, 255, 0.5);
  color: var(--text);
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.tm-ov-tile:hover { transform: translateY(-2px); background: rgba(255, 255, 255, 0.72); box-shadow: 0 4px 14px rgba(64, 158, 255, 0.18); }
.tm-ov-tile-num { font-size: 22px; font-weight: 800; line-height: 1.1; }
.tm-ov-tile-label { font-size: 13px; font-weight: 650; }
.tm-ov-tile-sub { color: var(--muted); font-size: 11.5px; }
.tm-ov-signals { display: grid; gap: 12px; margin-top: 14px; padding-top: 12px; border-top: 1px dashed rgba(148, 163, 184, 0.35); }
.tm-ov-signal { display: grid; gap: 6px; }
.tm-ov-signal-label { color: var(--muted); font-size: 12px; font-weight: 650; }
.tm-ov-signal-value { font-size: 13.5px; font-weight: 600; }

/* ---- 模型通道卡（0.9.0）：通道行 + 状态灯 ---- */
.tm-channel-row { display: grid; gap: 6px; padding: 10px 0; }
.tm-channel-head { display: flex; align-items: center; gap: 10px; }
.tm-channel-label { font-size: 13.5px; font-weight: 700; }
.tm-channel-light {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 2px 9px; border-radius: 999px; font-size: 11px; font-weight: 650;
}
.tm-channel-light::before { content: ""; width: 7px; height: 7px; border-radius: 999px; background: currentColor; }
.tm-light-ok { background: rgba(103, 194, 58, 0.14); color: #4d7c0f; }
.tm-light-dormant { background: rgba(245, 176, 77, 0.16); color: #b45309; }
.tm-light-off { background: rgba(148, 163, 184, 0.16); color: var(--muted); }
.tm-channel-divider { height: 1px; margin: 4px 0; background: rgba(148, 163, 184, 0.25); }
.tm-channel-warn {
  margin-top: 10px; padding: 10px 12px; border-radius: var(--radius-md);
  font-size: 12px; line-height: 1.6;
  background: rgba(245, 176, 77, 0.10); border: 1px solid rgba(245, 176, 77, 0.35);
  color: #92400e;
}

/* 连续心情胶囊：心情词文字直接可见；胶囊底色随 valence 内联（暖琥珀/灰蓝/中性灰），
   光晕大小与呼吸速度随 arousal 内联 */
.tm-mood-pill {
  position: relative; display: inline-flex; align-items: center; justify-content: center;
  padding: 3px 10px; border-radius: 999px; flex: 0 0 auto;
  box-shadow: 0 1px 3px rgba(2, 6, 23, 0.18);
}
.tm-mood-pill-word {
  position: relative; z-index: 1; color: #ffffff; font-size: 12.5px; font-weight: 700;
  line-height: 1.5; text-shadow: 0 1px 2px rgba(2, 6, 23, 0.28); white-space: nowrap;
}
.tm-mood-pill-halo {
  position: absolute; left: 50%; top: 50%; border-radius: 999px; pointer-events: none;
  background: inherit; opacity: 0.4;
  animation: tm-mood-breathe 3.4s ease-in-out infinite;
}
@keyframes tm-mood-breathe {
  0%, 100% { transform: translate(-50%, -50%) scale(0.55); opacity: 0.5; }
  50% { transform: translate(-50%, -50%) scale(1); opacity: 0.06; }
}

/* 当前心情仪表盘（情绪页）：大字心情词 + 双向愉悦度条 + 活跃度条 */
.tm-gauge { display: flex; flex-direction: column; gap: 10px; }
.tm-gauge-head { display: flex; align-items: baseline; gap: 12px; }
.tm-gauge-word { font-size: 22px; font-weight: 800; line-height: 1.3; }
.tm-gauge-hint { color: var(--muted); font-size: 12px; line-height: 1.5; }
.tm-gauge-row { display: flex; align-items: center; gap: 10px; }
.tm-gauge-label { flex: 0 0 52px; color: var(--muted); font-size: 12.5px; }
/* 轨道：渐变底色让"量程"本身可见——愉悦度左灰蓝→中灰→右暖琥珀，活跃度浅灰渐深；
   游标（marker）永远可见，静息态也有明确读数位置 */
.tm-gauge-track {
  position: relative; flex: 1; height: 12px; border-radius: 999px;
  box-shadow: inset 0 1px 2px rgba(2, 6, 23, 0.08);
}
.tm-gauge-track-bipolar {
  background: linear-gradient(90deg,
    rgba(110, 141, 171, 0.30) 0%, rgba(148, 163, 184, 0.14) 50%, rgba(245, 176, 77, 0.30) 100%);
}
.tm-gauge-track-plain {
  background: linear-gradient(90deg,
    rgba(100, 116, 139, 0.20) 0%, rgba(96, 165, 250, 0.24) 50%, rgba(244, 63, 94, 0.24) 100%);
}
.tm-gauge-zero {
  position: absolute; left: 50%; top: -1px; bottom: -1px; width: 1.5px;
  background: rgba(100, 116, 139, 0.55); transform: translateX(-50%);
}
.tm-gauge-baseline-tick {
  position: absolute; top: -1px; bottom: -1px; width: 1.5px;
  background: rgba(37, 99, 235, 0.55); transform: translateX(-50%);
}
.tm-gauge-fill {
  position: absolute; top: 0; bottom: 0; border-radius: 999px; opacity: 0.75;
  transition: left 0.3s ease, width 0.3s ease, background 0.3s ease;
}
.tm-gauge-marker {
  position: absolute; top: 50%; width: 14px; height: 14px; border-radius: 999px;
  transform: translate(-50%, -50%);
  border: 2px solid rgba(255, 255, 255, 0.95);
  box-shadow: 0 1px 4px rgba(2, 6, 23, 0.30), 0 0 6px rgba(255, 255, 255, 0.25);
  transition: left 0.3s ease, background 0.3s ease;
}
.tm-gauge-value {
  flex: 0 0 44px; text-align: right; font-size: 12.5px; font-weight: 700; color: var(--text);
  font-variant-numeric: tabular-nums;
}

.tm-warnstrip { padding: 8px 16px 0; }
.tm-warnstrip .neko-alert { padding: 5px 12px; border-radius: var(--radius-sm); font-size: 12.5px; line-height: 1.5; }

.tm-body { flex: 1; display: flex; min-height: 0; }
.tm-tabs {
  display: flex; flex-direction: column; gap: 4px; min-width: 76px; padding: 12px 6px;
  border-right: 1px solid rgba(255, 255, 255, 0.65);
  background: rgba(255, 255, 255, 0.42);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
}
.tm-tab {
  display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 10px 8px;
  border: 1px solid transparent; border-radius: var(--radius-md); background: transparent;
  color: var(--muted); font-size: 12.5px; cursor: pointer;
  transition: background 0.18s ease, color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease;
}
.tm-tab:hover { background: rgba(255, 255, 255, 0.55); transform: translateX(2px); box-shadow: 0 2px 8px rgba(96, 165, 250, 0.10); }
.tm-tab-active {
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.88) 0%, rgba(255, 255, 255, 0.62) 100%);
  border-color: rgba(255, 255, 255, 0.9);
  color: var(--text);
  box-shadow: inset 3px 0 0 var(--primary), inset 0 1px 0 rgba(255, 255, 255, 0.95), 0 4px 12px rgba(96, 165, 250, 0.16);
}
.tm-tab .tm-ico { opacity: 0.7; }
.tm-tab:hover .tm-ico { opacity: 0.9; }
.tm-tab-active .tm-ico { opacity: 1; }

.tm-content { flex: 1; min-width: 0; overflow-y: auto; padding: 16px 18px; }
.tm-pane { display: grid; gap: 12px; align-content: start; animation: tm-pane-in 280ms cubic-bezier(0.22, 0.61, 0.36, 1) both; }

.tm-card-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 12px 14px 0; }
.tm-card-title { margin: 0; font-size: 15px; font-weight: 720; }
.tm-card-body { padding: 12px 14px 14px; display: grid; gap: 12px; }

.tm-iconbtn {
  width: 34px; height: 34px; display: inline-flex; align-items: center; justify-content: center;
  border-radius: var(--radius-md); border: 1px solid transparent; background: transparent;
  font-size: 16px; line-height: 1; cursor: pointer; color: var(--muted);
  transition: background 0.18s ease, transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.tm-iconbtn:hover { background: rgba(64, 158, 255, 0.12); transform: translateY(-1px) rotate(18deg); }
.tm-iconbtn-active { background: rgba(64, 158, 255, 0.16); border-color: rgba(64, 158, 255, 0.40); color: var(--text); box-shadow: 0 4px 14px rgba(64, 158, 255, 0.25); }

.tm-cal-nav { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.tm-cal-label { font-weight: 650; }
.tm-cal-head, .tm-cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; }
.tm-cal-wd { color: var(--muted); font-size: 12px; text-align: center; padding: 2px 0; }
.tm-cal-cell {
  padding: 4px 0; text-align: center; border-radius: var(--radius-sm); font-size: 13px;
  border: 1px solid transparent;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease, background 0.3s ease, opacity 0.3s ease;
}
.tm-cal-cell[data-phase="menstrual"] { background: rgba(245, 108, 108, 0.16); }
.tm-cal-cell[data-phase="follicular"] { background: rgba(103, 194, 58, 0.14); }
.tm-cal-cell[data-phase="ovulatory"] { background: rgba(20, 184, 166, 0.14); }
/* 锚点前的日子按平稳期着色（cycle.py 的标签映射同语义），灰格改为中性底 */
.tm-cal-cell[data-phase="luteal"], .tm-cal-cell[data-phase="before_start"] { background: rgba(100, 116, 139, 0.10); }
.tm-cal-cell[data-today="1"] { border-color: var(--primary); font-weight: 700; }
.tm-cal-cell[data-future="1"] { opacity: 0.55; }
.tm-cal-cell[data-selectable="1"] { cursor: pointer; }
.tm-cal-cell[data-selectable="1"]:hover { transform: scale(1.09); box-shadow: 0 4px 14px rgba(64, 158, 255, 0.28); opacity: 1; }
.tm-cal-cell[data-picked="1"] {
  border-color: var(--primary); font-weight: 700; opacity: 1;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.35), 0 6px 16px rgba(64, 158, 255, 0.30);
  animation: tm-pick-pop 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}
.tm-cal-tidebar {
  display: block; width: 12px; height: 2.5px; margin: 2px auto 0;
  border-radius: 999px; background: var(--danger); opacity: 0.75;
}
.tm-legend { margin-top: 10px; display: flex; gap: 14px; flex-wrap: wrap; align-items: center; color: var(--muted); font-size: 12.5px; }
.tm-legend-item { display: inline-flex; align-items: center; gap: 5px; }
.tm-dot { width: 9px; height: 9px; border-radius: 999px; display: inline-block; }
.tm-dot-today { border: 1.5px solid var(--primary); }
.tm-cal-actions { display: inline-flex; align-items: center; gap: 8px; margin-left: auto; animation: tm-slide-in 0.25s cubic-bezier(0.22, 0.61, 0.36, 1) both; }
.tm-picked-label { color: var(--text); font-size: 12.5px; font-weight: 650; }
.tm-pick-hint { color: var(--primary); font-size: 12.5px; animation: tm-hint-pulse 1.6s ease-in-out infinite; }
.tm-cal-meta { color: var(--muted); font-size: 12px; }

.tm-tool { display: grid; gap: 8px; align-content: start; }
.tm-derived { color: var(--muted); font-size: 12.5px; line-height: 1.6; }

.tm-lanlan-list { display: grid; gap: 8px; }
.tm-lanlan-row {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 9px 12px; border-radius: var(--radius-md);
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.7);
}
.tm-lanlan-row[data-orphan="1"] { border-color: rgba(245, 108, 108, 0.35); background: rgba(245, 108, 108, 0.06); }
.tm-lanlan-name { font-weight: 650; }
.tm-lanlan-current { color: var(--primary); font-size: 12px; font-weight: 650; }
.tm-lanlan-meta { color: var(--muted); font-size: 12.5px; }
.tm-lanlan-spacer { margin-left: auto; }
/* 保存条吸底：设置页滚动到底部仍可见，磨砂底与面板一致；负外边距抵消 .tm-content 内边距实现通栏 */
.tm-save {
  position: sticky; bottom: 0; z-index: 5;
  display: flex; justify-content: flex-end;
  margin: 0 -18px -16px; padding: 10px 18px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.55) 0%, rgba(255, 255, 255, 0.78) 100%);
  -webkit-backdrop-filter: blur(12px) saturate(1.3);
  backdrop-filter: blur(12px) saturate(1.3);
  border-top: 1px solid rgba(255, 255, 255, 0.8);
  box-shadow: 0 -6px 18px rgba(96, 165, 250, 0.10);
}
/* 无 help 文案的 Field 预留一行 help 的高度（12px×1.5=18px），保证同一 Grid 内各词条等高、底部对齐 */
.tm-reserve-help::after { content: ""; display: block; height: 18px; }
/* Chromium 下同样式的 select 比 input 高 2px，统一控件高度，保证设置项等高对齐 */
.tm-pane .neko-input, .tm-pane .neko-select { height: 40px; }

.tm-diary { display: grid; gap: 10px; }
.tm-diary-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.tm-diary-count { color: var(--muted); font-size: 12.5px; }

/* 时光日记时间线：她的手记（暖调）与自动碎片（蓝调）混排，来源徽标 + 类型着色；
   按日期分组的组头吸顶，扫读时始终知道自己在看哪一天 */
.tm-timeline { display: grid; gap: 8px; }
.tm-day-group { display: grid; gap: 7px; }
.tm-day-head {
  position: sticky; top: 0; z-index: 2;
  display: flex; align-items: baseline; gap: 8px;
  padding: 5px 6px; margin: 0 -2px;
  border-radius: var(--radius-sm);
  font-size: 12.5px; font-weight: 750; color: var(--text);
  background: linear-gradient(180deg, rgba(248, 251, 255, 0.95) 0%, rgba(248, 251, 255, 0.82) 100%);
  -webkit-backdrop-filter: blur(8px);
  backdrop-filter: blur(8px);
}
.tm-day-count { font-weight: 550; color: var(--muted); font-size: 11.5px; }
.tm-tl-row {
  display: grid; gap: 5px; padding: 10px 12px; border-radius: var(--radius-md);
  border: 1px solid rgba(255, 255, 255, 0.7);
  background: rgba(245, 237, 220, 0.35);
}
.tm-tl-row[data-source="auto"] { background: rgba(219, 234, 254, 0.32); }
.tm-tl-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tm-tl-badge {
  display: inline-flex; align-items: center; gap: 3px; padding: 1px 8px; border-radius: 999px;
  font-size: 11px; font-weight: 650; line-height: 1.6;
  background: rgba(245, 176, 77, 0.18); color: var(--text);
}
.tm-tl-row[data-source="auto"] .tm-tl-badge { background: rgba(64, 158, 255, 0.14); }
.tm-tl-badge[data-kind="overstep"] { background: rgba(245, 108, 108, 0.16); }
.tm-tl-badge[data-kind="dislike"] { background: rgba(250, 204, 21, 0.20); }
.tm-tl-badge[data-kind="like"] { background: rgba(103, 194, 58, 0.15); }
.tm-tl-mood { color: var(--muted); font-size: 12px; font-weight: 650; }
.tm-tl-ts { color: var(--muted); font-size: 11.5px; font-variant-numeric: tabular-nums; }
.tm-tl-spacer { margin-left: auto; }
.tm-tl-delete {
  border: none; background: transparent; color: var(--muted); font-size: 11.5px; cursor: pointer;
  padding: 1px 6px; border-radius: var(--radius-sm); transition: background 0.15s ease, color 0.15s ease;
}
.tm-tl-delete:hover { background: rgba(245, 108, 108, 0.14); color: var(--danger, #f56c6c); }
/* 碎片原话的"他说的话"气泡：左侧竖线 + 淡蓝底，和她的正文一眼区分 */
.tm-tl-quote {
  padding: 6px 10px; border-left: 3px solid rgba(64, 158, 255, 0.45);
  background: rgba(64, 158, 255, 0.07); border-radius: 6px;
  font-size: 13px; font-weight: 650; line-height: 1.55;
}
.tm-tl-note { color: var(--muted); font-size: 12px; line-height: 1.5; }
.tm-tl-entry { font-size: 13px; line-height: 1.6; white-space: pre-wrap; }
.tm-diary-more { display: flex; justify-content: center; padding-top: 2px; }
.tm-diary-end { text-align: center; color: var(--muted); font-size: 12px; padding: 4px 0 2px; }

/* 个人日记工具行 + 目录：页码圆徽 + 日期区间 + 心情彩色圆点（复用状态栏配色算法） */
.tm-journal-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.tm-journal-actions { display: inline-flex; align-items: center; gap: 8px; }
.tm-toc { display: grid; gap: 8px; }
.tm-toc-row {
  display: flex; align-items: center; gap: 10px; text-align: left; width: 100%;
  padding: 10px 12px; border-radius: var(--radius-md); cursor: pointer;
  border: 1px solid rgba(255, 255, 255, 0.7); background: rgba(255, 255, 255, 0.5);
  transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
}
.tm-toc-row:hover { transform: translateX(3px); background: rgba(255, 255, 255, 0.72); box-shadow: 0 4px 14px rgba(64, 158, 255, 0.18); }
.tm-toc-no {
  flex: 0 0 auto; width: 36px; height: 36px; border-radius: 999px;
  display: inline-flex; align-items: center; justify-content: center; gap: 1px;
  background: rgba(245, 237, 220, 0.85); border: 1px solid rgba(231, 220, 195, 0.7);
  font-weight: 750; font-size: 11.5px;
}
.tm-toc-range { font-weight: 650; font-size: 13px; }
.tm-toc-meta { color: var(--muted); font-size: 12px; }
.tm-toc-legacy {
  padding: 1px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 650;
  background: rgba(148, 163, 184, 0.18); color: var(--muted);
}
.tm-toc-arrow { margin-left: auto; color: var(--muted); font-size: 16px; }
.tm-mood-dot {
  width: 10px; height: 10px; border-radius: 999px; display: inline-block; flex: 0 0 auto;
  box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.7);
}

/* 我的日记：素材进度条（下一份评价攒了多少轮）+ 设置子卡标题 */
.tm-review { display: grid; gap: 10px; }
.tm-review-progress { display: grid; gap: 6px; }
.tm-review-bar {
  height: 6px; border-radius: 999px; overflow: hidden;
  background: rgba(148, 163, 184, 0.22);
}
.tm-review-bar-fill {
  height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, rgba(64, 158, 255, 0.75), rgba(100, 181, 246, 0.9));
  transition: width 0.3s ease;
}
.tm-review-settings {
  margin-top: 14px; padding-top: 12px; display: grid; gap: 10px;
  border-top: 1px dashed rgba(148, 163, 184, 0.35);
}
.tm-subcard-title { font-size: 13px; font-weight: 700; }
.tm-number-input {
  width: 120px; padding: 6px 10px; border-radius: var(--radius-md);
  border: 1px solid rgba(148, 163, 184, 0.4); background: rgba(255, 255, 255, 0.6);
  font-size: 13px; color: var(--text);
}

/* 个人日记书页：纸质页 + 页眉（页码/日期区间/心情走向）+ 段落时间轴 + 翻页导航 */
.tm-book { display: grid; gap: 10px; }
.tm-book-topbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.tm-book-header { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
.tm-book-pageno { font-size: 14px; font-weight: 750; }
.tm-book-meta { color: var(--muted); font-size: 12px; }
.tm-book-trend { display: inline-flex; align-items: center; gap: 6px; color: var(--muted); font-size: 12px; }
/* 纸质阅读页：衬线字体 + 大行距，像她亲手写在本子上的字 */
.tm-book-entries {
  display: grid; gap: 10px; padding: 12px 14px; border-radius: var(--radius-md);
  background: linear-gradient(180deg, rgba(253, 250, 240, 0.75) 0%, rgba(250, 245, 232, 0.6) 100%);
  border: 1px solid rgba(231, 220, 195, 0.6);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}
.tm-paper { font-family: Georgia, "Noto Serif SC", "Songti SC", "SimSun", serif; }
.tm-book-entry { display: grid; gap: 3px; }
.tm-book-entry + .tm-book-entry { border-top: 1px dashed rgba(180, 165, 130, 0.35); padding-top: 10px; }
.tm-book-entry-ts { color: rgba(146, 132, 106, 0.9); font-size: 11px; font-variant-numeric: tabular-nums; }
.tm-book-entry-text { font-size: 13.5px; line-height: 1.95; white-space: pre-wrap; color: #3f3a2f; }
.tm-book-nav { display: flex; align-items: center; justify-content: center; gap: 12px; }
.tm-book-indicator { color: var(--muted); font-size: 12.5px; font-variant-numeric: tabular-nums; min-width: 48px; text-align: center; }

@keyframes tm-pane-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes tm-slide-in { from { opacity: 0; transform: translateX(12px); } to { opacity: 1; transform: none; } }
@keyframes tm-pick-pop { from { transform: scale(0.85); } to { transform: scale(1); } }
@keyframes tm-breathe { 0%, 100% { box-shadow: 0 0 0 0 rgba(64, 158, 255, 0.45); } 50% { box-shadow: 0 0 0 7px rgba(64, 158, 255, 0); } }
@keyframes tm-hint-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
@keyframes tm-ring-surge { from { transform: rotate(0deg); opacity: 1; } to { transform: rotate(340deg); opacity: 0; } }
@keyframes tm-center-pop { from { opacity: 0; transform: scale(0.72); } to { opacity: 1; transform: scale(1); } }

@media (prefers-color-scheme: dark) {
  .neko-page {
    background:
      radial-gradient(900px 460px at 88% -10%, rgba(99, 102, 241, 0.09), transparent 60%),
      radial-gradient(800px 420px at -8% 108%, rgba(56, 189, 248, 0.06), transparent 58%),
      linear-gradient(160deg, #0d1526 0%, #111b2f 50%, #0d1626 100%);
  }
  .neko-card, .tm-card {
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.72) 0%, rgba(30, 41, 59, 0.58) 100%);
    border-color: rgba(148, 163, 184, 0.16);
    box-shadow: 0 1px 2px rgba(2, 6, 23, 0.3), 0 10px 30px rgba(2, 6, 23, 0.4), inset 0 1px 0 rgba(148, 163, 184, 0.12);
  }
  .neko-input, .neko-select, .neko-textarea { background: rgba(15, 23, 42, 0.55); }
  .neko-button {
    background: linear-gradient(180deg, rgba(51, 65, 85, 0.6) 0%, rgba(30, 41, 59, 0.45) 100%);
    border-color: rgba(148, 163, 184, 0.2);
    box-shadow: 0 1px 2px rgba(2, 6, 23, 0.25), 0 4px 12px rgba(2, 6, 23, 0.3), inset 0 1px 0 rgba(148, 163, 184, 0.14);
  }
  .neko-button:hover:not(:disabled) {
    background: linear-gradient(180deg, rgba(51, 65, 85, 0.75) 0%, rgba(30, 41, 59, 0.58) 100%);
    box-shadow: 0 2px 4px rgba(2, 6, 23, 0.3), 0 8px 20px rgba(2, 6, 23, 0.4), inset 0 1px 0 rgba(148, 163, 184, 0.18);
  }
  .neko-button[data-tone="primary"] { background: linear-gradient(180deg, rgba(64, 158, 255, 0.26) 0%, rgba(64, 158, 255, 0.14) 100%); border-color: rgba(64, 158, 255, 0.45); }
  .tm-statusbar {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.62) 0%, rgba(15, 23, 42, 0.5) 100%);
    border-bottom-color: rgba(148, 163, 184, 0.14);
    box-shadow: 0 6px 20px rgba(2, 6, 23, 0.35), inset 0 1px 0 rgba(148, 163, 184, 0.1);
  }
  .tm-save {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.5) 0%, rgba(15, 23, 42, 0.72) 100%);
    border-top-color: rgba(148, 163, 184, 0.14);
    box-shadow: 0 -6px 18px rgba(2, 6, 23, 0.35);
  }
  .tm-ring-dot { background: rgba(148, 163, 184, 0.35); }
  .tm-ring-dot:hover { background: rgba(148, 163, 184, 0.6); }
  .tm-ring-dot-active { background: var(--primary); }
  .tm-tabs { background: rgba(15, 23, 42, 0.4); border-right-color: rgba(148, 163, 184, 0.12); }
  .tm-lanlan-row { background: rgba(15, 23, 42, 0.45); border-color: rgba(148, 163, 184, 0.16); }
  .tm-lanlan-row[data-orphan="1"] { border-color: rgba(245, 108, 108, 0.3); background: rgba(245, 108, 108, 0.08); }
  .tm-tab-active {
    background: linear-gradient(180deg, rgba(51, 65, 85, 0.8) 0%, rgba(30, 41, 59, 0.6) 100%);
    border-color: rgba(148, 163, 184, 0.22);
    box-shadow: inset 3px 0 0 var(--primary), inset 0 1px 0 rgba(148, 163, 184, 0.15), 0 4px 12px rgba(2, 6, 23, 0.35);
  }
  .tm-ring-glow { background: radial-gradient(closest-side, rgba(147, 197, 253, 0.28), rgba(147, 197, 253, 0) 74%); }
  .tm-ring-orbit { border-color: rgba(148, 163, 184, 0.28); }
  .tm-ring-phase-dot { border-color: rgba(15, 23, 42, 0.85); }
  .tm-moon-pill { background: rgba(15, 23, 42, 0.78); box-shadow: 0 1px 4px rgba(2, 6, 23, 0.5); }
  /* 暗色主题的月盘暗面/扫掠暗盘：深空玻璃（亮色主题的浅灰玻璃在暗底上会刺眼） */
  .tm-moon-shadow { background: radial-gradient(circle at 36% 32%, #2a3548, #1e293b 80%); box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.10); }
  .tm-moon-base { background: radial-gradient(circle at 36% 32%, rgba(148, 163, 184, 0.06), rgba(100, 116, 139, 0.10) 80%); }
  .tm-ring-marker { border-color: rgba(15, 23, 42, 0.9); }
  .tm-mood-pill { box-shadow: 0 1px 3px rgba(2, 6, 23, 0.5); }
  .tm-gauge-track { box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.35); }
  .tm-gauge-track-bipolar {
    background: linear-gradient(90deg,
      rgba(110, 141, 171, 0.38) 0%, rgba(148, 163, 184, 0.16) 50%, rgba(245, 176, 77, 0.38) 100%);
  }
  .tm-gauge-track-plain {
    background: linear-gradient(90deg,
      rgba(148, 163, 184, 0.18) 0%, rgba(96, 165, 250, 0.30) 50%, rgba(244, 63, 94, 0.30) 100%);
  }
  .tm-gauge-zero { background: rgba(148, 163, 184, 0.55); }
  .tm-gauge-baseline-tick { background: rgba(147, 197, 253, 0.6); }
  .tm-gauge-marker { border-color: rgba(15, 23, 42, 0.9); box-shadow: 0 1px 4px rgba(2, 6, 23, 0.6); }
  .tm-tl-row { border-color: rgba(148, 163, 184, 0.16); background: rgba(30, 27, 22, 0.45); }
  .tm-tl-row[data-source="auto"] { background: rgba(18, 30, 48, 0.5); }
  .tm-day-head {
    color: var(--text);
    background: linear-gradient(180deg, rgba(13, 21, 38, 0.95) 0%, rgba(13, 21, 38, 0.82) 100%);
  }
  .tm-toc-row { border-color: rgba(148, 163, 184, 0.16); background: rgba(15, 23, 42, 0.45); }
  .tm-toc-row:hover { background: rgba(15, 23, 42, 0.68); }
  .tm-toc-no { background: rgba(38, 33, 24, 0.8); border-color: rgba(180, 165, 130, 0.3); }
  .tm-mood-dot { box-shadow: 0 0 0 2px rgba(15, 23, 42, 0.8); }
  .tm-review-bar { background: rgba(148, 163, 184, 0.18); }
  .tm-review-settings { border-top-color: rgba(148, 163, 184, 0.22); }
  .tm-number-input { background: rgba(15, 23, 42, 0.5); border-color: rgba(148, 163, 184, 0.3); color: var(--text); }
  .tm-book-entries {
    background: linear-gradient(180deg, rgba(38, 33, 24, 0.7) 0%, rgba(32, 28, 20, 0.6) 100%);
    border-color: rgba(180, 165, 130, 0.28);
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.08);
  }
  .tm-book-entry-text { color: #d8d2c2; }
  .tm-book-entry-ts { color: rgba(168, 155, 126, 0.9); }

}

@media (prefers-reduced-motion: reduce) {
  .tm-pane, .tm-cal-actions, .tm-ring-marker, .tm-pick-hint, .tm-cal-cell,
  .tm-ring-wrap, .tm-moon-pill, .tm-mood-pill-halo { animation: none !important; transition: none !important; }
  .tm-ring-surge-sweep { display: none !important; }
}

/* ============================================================
   面板外观（自定义背景图）
   ============================================================ */
/* 背景层绝对定位沉底：内容三块（状态栏/警示条/主体）抬高 z-index 盖在其上；
   dim 层用不透明深色底 + 内联 opacity 控制压暗程度，保证磨砂卡片上文字可读 */
.tm-bg {
  position: absolute; inset: 0; z-index: 0; pointer-events: none;
  background-size: cover; background-position: center; background-repeat: no-repeat;
}
.tm-bg-dim { position: absolute; inset: 0; background: #0a0f1c; }
.tm-statusbar, .tm-body, .tm-warnstrip { position: relative; z-index: 1; }
/* 有背景时页面底色换深色基底（图片会铺满，基底只防白边透出），亮暗模式同色 */
.neko-page.tm-has-bg { background: #0e1524; }
/* 透明主题强化：自定义背景下磨砂卡片加深模糊与饱和，叠出更通透的玻璃感 */
.tm-has-bg .neko-card, .tm-has-bg .tm-card {
  -webkit-backdrop-filter: blur(16px) saturate(1.35);
  backdrop-filter: blur(16px) saturate(1.35);
}
.tm-has-bg .tm-statusbar {
  -webkit-backdrop-filter: blur(16px) saturate(1.35);
  backdrop-filter: blur(16px) saturate(1.35);
}
.tm-has-bg .tm-tabs {
  -webkit-backdrop-filter: blur(14px);
  backdrop-filter: blur(14px);
}

/* 外观卡：预览区与操作行 */
.tm-appearance { display: grid; gap: 10px; }
.tm-appearance-actions { display: flex; gap: 8px; align-items: center; }
.tm-bg-preview {
  position: relative; height: 110px; border-radius: var(--radius-md); overflow: hidden;
  background-size: cover; background-position: center; background-repeat: no-repeat;
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 4px 14px rgba(2, 6, 23, 0.12);
}
.tm-bg-preview-dim { position: absolute; inset: 0; background: #0a0f1c; }

/* ============================================================
   纯 CSS 线框图标（hosted 运行时不支持 SVG，颜色随 currentColor）
   ============================================================ */
.tm-ico { position: relative; display: inline-block; width: 16px; height: 16px; flex: 0 0 auto; }
/* 日历：圆角边框 + 顶部横线 */
.tm-ico-calendar { border: 1.5px solid currentColor; border-radius: 3px; }
.tm-ico-calendar::before {
  content: ""; position: absolute; left: 1px; right: 1px; top: 3.5px;
  height: 1.5px; background: currentColor;
}
/* 周期：圆环 + 轨道上的小点（呼应状态栏圆环的今日标记） */
.tm-ico-cycle { border: 1.5px solid currentColor; border-radius: 999px; }
.tm-ico-cycle::after {
  content: ""; position: absolute; right: 0; top: 0;
  width: 4px; height: 4px; border-radius: 999px; background: currentColor;
}
/* 注入：消息气泡里两行字 */
.tm-ico-inject { border: 1.5px solid currentColor; border-radius: 4px; }
.tm-ico-inject::before {
  content: ""; position: absolute; left: 2.5px; right: 2.5px; top: 4px;
  height: 1.5px; background: currentColor;
}
.tm-ico-inject::after {
  content: ""; position: absolute; left: 2.5px; right: 5.5px; top: 8px;
  height: 1.5px; background: currentColor;
}
/* 情绪：半填充圆（愉悦度双向条的冷暖两极意象） */
.tm-ico-mood {
  border: 1.5px solid currentColor; border-radius: 999px;
  background: linear-gradient(90deg, currentColor 50%, transparent 50%);
}
/* 总览：四象限网格（仪表盘意象） */
.tm-ico-overview {
  background:
    linear-gradient(currentColor, currentColor) 0 0 / 100% 1.5px no-repeat,
    linear-gradient(currentColor, currentColor) 0 100% / 100% 1.5px no-repeat,
    linear-gradient(currentColor, currentColor) 0 0 / 1.5px 100% no-repeat,
    linear-gradient(currentColor, currentColor) 100% 0 / 1.5px 100% no-repeat,
    linear-gradient(currentColor, currentColor) 50% 35% / 25% 1.5px no-repeat,
    linear-gradient(currentColor, currentColor) 35% 50% / 1.5px 30% no-repeat;
}
/* 设置：齿轮意象（外圈 + 中心圆点） */
.tm-ico-settings { border: 1.5px solid currentColor; border-radius: 999px; }
.tm-ico-settings::after {
  content: ""; position: absolute; left: 50%; top: 50%;
  width: 4px; height: 4px; margin: -2px 0 0 -2px;
  border-radius: 999px; background: currentColor;
}
/* 日记：本子轮廓 + 左侧装订线 */
.tm-ico-diary { border: 1.5px solid currentColor; border-radius: 2px 4px 4px 2px; }
.tm-ico-diary::before {
  content: ""; position: absolute; left: 3px; top: 1px; bottom: 1px;
  width: 1.5px; background: currentColor;
}
/* 管理：三条滑轨 + 两个滑块圆点 */
.tm-ico-manage {
  background:
    linear-gradient(currentColor, currentColor) 0 3px / 100% 1.5px no-repeat,
    linear-gradient(currentColor, currentColor) 0 7.25px / 100% 1.5px no-repeat,
    linear-gradient(currentColor, currentColor) 0 11.5px / 100% 1.5px no-repeat;
}
.tm-ico-manage::before {
  content: ""; position: absolute; left: 2px; top: 1.25px;
  width: 3.5px; height: 3.5px; border-radius: 999px; background: currentColor;
}
.tm-ico-manage::after {
  content: ""; position: absolute; right: 2px; top: 9.5px;
  width: 3.5px; height: 3.5px; border-radius: 999px; background: currentColor;
}

/* ---- 时光页 · 相处统计（1.1.0 · 磨砂玻璃精致化）---- */
/* 里程碑氛围卡：包住 hero 行 + 四个统计小卡的对角双色氛围容器 */
.tm-hero-card {
  position: relative;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.55) 0%, rgba(255, 255, 255, 0.35) 100%);
  border: 1px solid rgba(255, 255, 255, 0.75);
  /* 双色落影：只留若有若无的微光浮起感（不做明显影块） */
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    0 4px 14px rgba(245, 176, 77, 0.04),
    0 4px 14px rgba(96, 165, 250, 0.05);
}
/* 氛围光斑：左上暖橙 / 右下冷蓝（与橙色对称的强度与尺寸），
   伪元素承载并极慢呼吸（错开半拍）；内容经 z-index 置于光斑之上 */
.tm-hero-card::before, .tm-hero-card::after {
  content: ""; position: absolute; inset: 0; border-radius: inherit;
  pointer-events: none; z-index: 0;
}
.tm-hero-card::before {
  background: radial-gradient(240px 120px at 12% 0%, rgba(245, 176, 77, 0.10), transparent 70%);
  animation: tm-hero-glow 9s ease-in-out infinite;
}
.tm-hero-card::after {
  background: radial-gradient(240px 120px at 88% 100%, rgba(96, 165, 250, 0.10), transparent 70%);
  animation: tm-hero-glow 9s ease-in-out infinite;
  animation-delay: -4.5s;
}
@keyframes tm-hero-glow { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
.tm-hero-card > * { position: relative; z-index: 1; }

/* ---- 自适应悬停提示（AdaptiveTip）：fixed 定位，不受祖先 overflow 裁剪 ----
   坐标由悬停瞬间的视口量测写入 style；上弹时底边对齐 top、下翻时顶边对齐 top */
/* 包裹层需保留盒模型（量测坐标用）：inline-block 适配 flex/块级/行内各宿主布局 */
.tm-tip-wrap { display: inline-block; vertical-align: top; }
.tm-tip {
  position: fixed; z-index: 10000; transform: translate(-50%, -100%);
  max-width: 240px; padding: 5px 9px; border-radius: 8px;
  background: rgba(15, 23, 42, 0.94); color: #e6edf7;
  font-size: 11px; line-height: 1.45; text-align: center;
  box-shadow: 0 4px 14px rgba(2, 6, 23, 0.35);
  pointer-events: none; white-space: normal;
}
.tm-tip-below { transform: translate(-50%, 0); }
/* hero 数字区：相伴天数大数字 + 纪念日进度环（氛围卡内上半区） */
.tm-hero {
  display: flex; align-items: center; justify-content: space-between; gap: 18px;
  flex-wrap: wrap; margin-bottom: 12px;
}
.tm-hero-days { display: flex; flex-direction: column; gap: 2px; cursor: default; }
.tm-hero-days-value {
  font-size: 40px; font-weight: 800; line-height: 1; letter-spacing: -0.5px;
  background: linear-gradient(180deg, #3c4a5e 0%, #5a6b82 100%);
  -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  font-variant-numeric: tabular-nums;
}
.tm-hero-days-label { font-size: 12.5px; color: var(--muted); font-weight: 600; }
/* 纪念日进度环：conic-gradient 填充 + 玻璃内芯（数字居中） */
.tm-hero-ring { display: flex; flex-direction: column; align-items: center; gap: 4px; cursor: default; }
.tm-hero-ring-track {
  position: relative; width: 64px; height: 64px; border-radius: 999px;
  display: flex; align-items: center; justify-content: center;
  box-shadow: 0 2px 10px rgba(245, 176, 77, 0.22);
}
.tm-hero-ring-inner {
  position: absolute; inset: 6px; border-radius: 999px;
  display: flex; align-items: baseline; justify-content: center; gap: 1px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.92) 0%, rgba(255, 255, 255, 0.78) 100%);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 1), 0 1px 3px rgba(100, 116, 139, 0.18);
}
.tm-hero-ring-num { font-size: 19px; font-weight: 800; line-height: 64px; font-variant-numeric: tabular-nums; }
.tm-hero-ring-unit { font-size: 10px; color: var(--muted); line-height: 64px; }
.tm-hero-ring-label { font-size: 11px; color: var(--muted); font-weight: 600; }
/* 统计玻璃小卡（氛围卡内底边距由卡片接管） */
.tm-stat-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 16px; }
.tm-hero-card .tm-stat-strip { margin-bottom: 0; }
.tm-stat-cell {
  display: flex; flex-direction: column; align-items: center; gap: 2px;
  padding: 10px 4px; border-radius: 10px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.55) 0%, rgba(255, 255, 255, 0.32) 100%);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
  cursor: default;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}
.tm-stat-cell:hover { transform: translateY(-1px); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.95), 0 4px 12px rgba(96, 165, 250, 0.14); }
.tm-stat-value { font-size: 17px; font-weight: 750; line-height: 1.2; font-variant-numeric: tabular-nums; }
.tm-stat-label { font-size: 11px; color: var(--muted); }
@media (max-width: 560px) {
  .tm-stat-strip { grid-template-columns: repeat(2, 1fr); }
}

/* ---- 相处徽章墙（成就卡片式 2.0）：横向 4 列卡片（窄面板降列），月光蓝主调 ----
   天数类按难度升级月相（新月→半月→满月→星拱月→潮汐月），
   事件类专属图形（羽毛笔/书页/信封）；未解锁整卡灰化剪影 + 进度条 */
/* 徽章墙横向排列：4 列 × 2 行，窄面板逐级降列 */
.tm-badge-wall { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.tm-ach {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px; border-radius: 12px;
  background: rgba(148, 163, 184, 0.06); border: 1px solid rgba(148, 163, 184, 0.16);
  cursor: default;
  transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease;
}
.tm-ach:hover { transform: translateY(-2px); box-shadow: 0 6px 16px rgba(2, 6, 23, 0.10); }
.tm-ach-on {
  background:
    radial-gradient(140px 70px at 18% 0%, rgba(96, 165, 250, 0.14), transparent 70%),
    rgba(96, 165, 250, 0.05);
  border-color: rgba(96, 165, 250, 0.42);
}
.tm-ach-on:hover { box-shadow: 0 6px 18px rgba(96, 165, 250, 0.22); }
/* 左侧圆形图标底座：深海军蓝夜空底，解锁态星光点点 */
.tm-ach-icon {
  position: relative; flex: 0 0 46px; width: 46px; height: 46px; border-radius: 999px;
  display: flex; align-items: center; justify-content: center;
  background: radial-gradient(circle at 36% 30%, #2b4a72 0%, #17294a 58%, #0c1830 100%);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.18), inset 0 -2px 5px rgba(2, 6, 23, 0.5), 0 1px 3px rgba(2, 6, 23, 0.18);
}
.tm-ach-on .tm-ach-icon {
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.28), inset 0 -2px 5px rgba(2, 6, 23, 0.5), 0 0 12px rgba(125, 180, 255, 0.35);
}
.tm-ach-on .tm-ach-icon::before {
  content: ""; position: absolute; inset: 0; border-radius: 999px; pointer-events: none;
  background-image:
    radial-gradient(circle 1px, rgba(226, 240, 255, 0.95) 50%, transparent 52%),
    radial-gradient(circle 0.8px, rgba(226, 240, 255, 0.8) 50%, transparent 52%),
    radial-gradient(circle 0.7px, rgba(226, 240, 255, 0.7) 50%, transparent 52%);
  background-position: 22% 24%, 76% 20%, 70% 78%;
  background-repeat: no-repeat;
}
.tm-ach-body { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.tm-ach-name { font-size: 12px; font-weight: 700; line-height: 1.25; }
.tm-ach-sub { font-size: 10.5px; color: var(--muted); line-height: 1.25; }
.tm-ach-on .tm-ach-sub { color: rgba(96, 140, 200, 0.95); }
/* 相伴进度条：未解锁时显示当前相伴天数占目标的进度 */
.tm-ach-bar {
  display: block; height: 3px; margin-top: 2px; border-radius: 999px;
  background: rgba(148, 163, 184, 0.28); overflow: hidden;
}
.tm-ach-bar-fill {
  display: block; height: 100%; border-radius: 999px;
  background: linear-gradient(90deg, rgba(96, 165, 250, 0.5), rgba(96, 165, 250, 0.85));
}
/* 未解锁：整卡灰化剪影。图标底座换成中性灰夜空（不白不黑），
   不再用深海军蓝灰化后的偏黑底 */
.tm-ach:not(.tm-ach-on) .tm-ach-icon {
  filter: grayscale(1);
  background: radial-gradient(circle at 36% 30%, #d2d7df 0%, #a9b1bd 58%, #8b93a1 100%);
  box-shadow: inset 0 1px 1px rgba(255, 255, 255, 0.4), inset 0 -2px 5px rgba(51, 65, 85, 0.28), 0 1px 3px rgba(2, 6, 23, 0.12);
}
.tm-ach:not(.tm-ach-on) .tm-ach-bar-fill { background: rgba(148, 163, 184, 0.6); }

/* ---- 徽章图形：月相五档 + 羽毛笔/书页/信封（配色走月光银蓝）---- */
.tm-glyph { position: relative; display: block; width: 26px; height: 26px; }
.tm-ach-on .tm-glyph { color: #eaf3ff; }
.tm-ach:not(.tm-ach-on) .tm-glyph { color: rgba(160, 174, 192, 0.8); }
/* 新月：银蓝圆盘 + mask 切出一弯（镂空处透出底座夜空色，不产生色差） */
.tm-glyph-crescent {
  border-radius: 999px;
  background: radial-gradient(circle at 34% 30%, #ffffff 0%, #dcebff 45%, #9cc2ef 100%);
  box-shadow: 0 0 6px rgba(190, 220, 255, 0.55);
  -webkit-mask: radial-gradient(circle at 74% 24%, transparent 52%, #000 54%);
  mask: radial-gradient(circle at 74% 24%, transparent 52%, #000 54%);
}
.tm-ach:not(.tm-ach-on) .tm-glyph-crescent { box-shadow: none; }
/* 半月：右半亮面 */
.tm-glyph-half {
  border-radius: 999px;
  background: linear-gradient(90deg, rgba(148, 178, 214, 0.3) 0 50%, #dcebff 50% 62%, #9cc2ef 100%);
  box-shadow: 0 0 6px rgba(190, 220, 255, 0.45);
}
.tm-ach:not(.tm-ach-on) .tm-glyph-half { box-shadow: none; }
/* 满月：圆满亮盘 + 光晕 */
.tm-glyph-full {
  border-radius: 999px;
  background: radial-gradient(circle at 36% 30%, #ffffff 0%, #e8f2ff 42%, #b6d2f2 75%, #8fb6e4 100%);
  box-shadow: 0 0 8px rgba(200, 228, 255, 0.65);
}
.tm-ach:not(.tm-ach-on) .tm-glyph-full { box-shadow: none; }
/* 星拱月：满月居中 + 环拱星光点 */
.tm-glyph-orbit { width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; }
.tm-glyph-orbit .tm-glyph-full { width: 17px; height: 17px; }
.tm-glyph-orbit::before, .tm-glyph-orbit::after {
  content: ""; position: absolute; border-radius: 999px;
  background: #dcebff; box-shadow: 0 0 4px rgba(200, 228, 255, 0.8);
}
.tm-glyph-orbit::before { left: 1px; top: 7px; width: 3px; height: 3px; }
.tm-glyph-orbit::after { right: 2px; top: 17px; width: 2.5px; height: 2.5px; }
/* 潮汐月：新月上浮 + 两道涌动潮水线 */
.tm-glyph-tide { width: 30px; height: 30px; }
.tm-glyph-tide .tm-glyph-crescent {
  position: absolute; left: 50%; top: 1px; width: 15px; height: 15px; margin-left: -7.5px;
}
.tm-glyph-wave {
  position: absolute; left: 3px; width: 24px; height: 3px; border-radius: 2px;
  background: linear-gradient(90deg, transparent, #9cc2ef 18%, #e8f2ff 50%, #9cc2ef 82%, transparent);
}
.tm-glyph-w1 { bottom: 7px; }
.tm-glyph-w2 { bottom: 2px; left: 6px; width: 18px; opacity: 0.65; }
/* 羽毛笔：斜笔杆（圆角长条旋转）+ 笔尖三角 */
.tm-glyph-quill-body {
  position: absolute; left: 5px; top: 2px; width: 5.5px; height: 16px;
  border-radius: 3px 3px 1px 1px;
  background: currentColor; opacity: 0.9;
  transform: rotate(32deg);
}
.tm-glyph-quill-nib {
  position: absolute; left: 10.5px; top: 14.5px; width: 0; height: 0;
  border-left: 2.6px solid transparent; border-right: 2.6px solid transparent;
  border-top: 5px solid currentColor;
  transform: rotate(32deg);
}
/* 书页：摊开双页（两个带折角的梯形）+ 两行字线 */
.tm-glyph-book-page {
  position: absolute; top: 5px; width: 10px; height: 14px;
  background: currentColor; opacity: 0.85;
}
.tm-glyph-book-left { left: 2px; clip-path: polygon(0 12%, 100% 0, 100% 100%, 0 100%); }
.tm-glyph-book-right { right: 2px; clip-path: polygon(0 0, 100% 12%, 100% 100%, 0 100%); }
.tm-glyph-book-line { position: absolute; height: 1.6px; border-radius: 1px; background: rgba(23, 41, 74, 0.85); }
.tm-glyph-book-l1 { left: 4.5px; top: 10px; width: 6.5px; }
.tm-glyph-book-l2 { left: 13px; top: 10px; width: 6.5px; }
/* 信封：矩形底 + 盖片三角 + 封口圆点 */
.tm-glyph-letter { border: 1.8px solid currentColor; border-radius: 3px; opacity: 1; }
.tm-glyph-letter-flap {
  position: absolute; left: 0; top: 0; width: 0; height: 0;
  border-left: 10.5px solid transparent; border-right: 10.5px solid transparent;
  border-top: 7px solid currentColor; opacity: 0.85;
}
.tm-glyph-letter-seal {
  position: absolute; left: 50%; top: 12px; width: 4.5px; height: 4.5px; margin-left: -2.25px;
  border-radius: 999px; background: currentColor;
}
@media (max-width: 720px) {
  .tm-badge-wall { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 440px) {
  .tm-badge-wall { grid-template-columns: 1fr; }
}

/* ---- 热力图（GitHub 贡献图布局：列=周，行=星期几）----
   tm-gh = 网格骨架：月行（顶）+ 星期列（左）+ 周列区；
   tm-heat-cell 延续双层表达（深浅=互动量、格底色条=心情）。
   自适应无滚动（GitHub 同款观感）：滚动容器声明 container-type，
   格子/间距用 cqw 弹性伸缩——49 列在常规面板宽度下恰好填满。
   overflow-x 用 hidden 而非 auto：自适应公式已保证装得下，物理上
   禁止滚动条出现（Electron 面板环境对 overflow:auto 的原生滚动条
   渲染无法被 ::-webkit-scrollbar 完全约束——沙箱 iframe 里实测
   无溢出但仍出现蓝灰色横条的案例）；代价是极窄面板（<464px，格子
   已到 7px 下限）时右侧裁掉少许列，可接受。
   cqw 兼容性：宿主 Plugin Manager 自身已用 container-type/@container
   （PluginCard.vue），面板 iframe 同一 Chromium 内核，安全；不支持时
   clamp() 回退 min 参数（7px 固定格），布局仍成立 */
.tm-heat-scroll { overflow-x: hidden; padding-bottom: 2px; container-type: inline-size; }
/* 格子尺寸与间距变量：随容器宽伸缩。真实宽度账本（实测核对）：
   总宽 = 星期列 18 + body gap 4 + 49 列×(格+gap) − 尾列 1 个 gap
   ⇒ 可用 = 容器宽 − 22 − 48×gap。gap 固定 2px（clamp 下限）时每列
   可摊 = (100cqw − 118px) ÷ 49。格子 7px 下限 ⇒ 容器 <461px 才滚动。
   面板 606px → 格 ~9.9px；720px+ → 11px 顶格 */
.tm-gh {
  --tm-gh-cell: clamp(7px, calc((100cqw - 121px) / 49), 11px);
  --tm-gh-gap: 1.5px;
  display: inline-flex; flex-direction: column; gap: 1px;
}
/* 热力图卡的紧凑间距（第三档·极限）：header 6/0 + body 4/6 —— 上下缓冲压到
   视觉贴边（卡片有圆角边框做天然边界，不需要大 padding 撑呼吸感）。
   月报/徽章卡维持默认 —— 阅读型内容需要呼吸感 */
.tm-heat-card .neko-card-header { padding-top: 6px; padding-bottom: 0; }
.tm-heat-card .neko-card-body { padding-top: 4px; padding-bottom: 6px; }
/* 顶部月份行：每列一个等宽槽，只有含新月 1 号的槽渲染标签；
   高度与格子完全等高（文字用绝对定位垂直居中，不占额外行高位） */
.tm-gh-monthrow { display: flex; gap: var(--tm-gh-gap); }
.tm-gh-corner { width: 22px; flex: 0 0 22px; }
.tm-gh-monthslot { width: var(--tm-gh-cell); flex: 0 0 var(--tm-gh-cell); height: var(--tm-gh-cell); position: relative; }
/* 月份标签（"10月"≈16px）比格子槽（8~11px）宽，absolute 默认从槽左缘向右伸出 ~5px；
   在网格最右缘（最后一个槽）会撑大 scrollWidth 制造假滚动条——末槽标签改为右对齐
   （right:0 向左展开），完整显示且不越出容器右缘；中间槽的伸出被右侧相邻列自然覆盖，
   不会累计到 scrollWidth 之外。垂直：top/bottom 0 + line-height 撑格高，文字随格居中 */
.tm-gh-monthslot:last-child .tm-gh-month { left: auto; right: 0; }
.tm-gh-month {
  position: absolute; left: 0; top: 0; white-space: nowrap;
  font-size: 9.5px; color: var(--muted); font-weight: 600;
  line-height: var(--tm-gh-cell);
}
/* 主体：左侧星期标签列 + 周列区 */
.tm-gh-body { display: flex; gap: 4px; }
.tm-gh-wdcol { display: flex; flex-direction: column; gap: var(--tm-gh-gap); width: 18px; flex: 0 0 18px; }
.tm-gh-wd {
  height: var(--tm-gh-cell); font-size: 9.5px; color: var(--muted); line-height: 11px;
  display: flex; align-items: center; user-select: none;
}
.tm-gh-wd-empty { visibility: hidden; }
.tm-gh-cols { display: flex; gap: var(--tm-gh-gap); }
.tm-gh-col { display: flex; flex-direction: column; gap: var(--tm-gh-gap); }
/* 未来/窗口外占位：透明格保持列高对齐 */
.tm-heat-future { display: inline-block; width: var(--tm-gh-cell); height: var(--tm-gh-cell); }
/* 格子本体 */
.tm-heat-cell {
  position: relative; display: inline-block;
  width: var(--tm-gh-cell); height: var(--tm-gh-cell); border-radius: 3px;
  background: rgba(148, 163, 184, 0.16); cursor: default;
  transition: transform 0.12s ease;
}
.tm-heat-cell:hover { transform: scale(1.25); }
.tm-heat-lv1 { background: rgba(96, 165, 250, 0.32); }
.tm-heat-lv2 { background: rgba(96, 165, 250, 0.55); }
.tm-heat-lv3 { background: rgba(96, 165, 250, 0.78); }
.tm-heat-lv4 { background: rgba(96, 165, 250, 1); }
/* 心情色条：格子底部亮条，正=暖琥珀、负=灰蓝、无采样=不亮；
   尺寸改为百分比随格子缩放（cqw 下格子是 7~11px 弹性值，固定像素会溢出小格） */
.tm-heat-mood {
  position: absolute; left: 18%; right: 18%; bottom: 12%; height: 24%;
  border-radius: 1.5px; pointer-events: none;
}
.tm-heat-mood-warm { background: rgb(245, 176, 77); box-shadow: 0 0 3px rgba(245, 176, 77, 0.65); }
.tm-heat-mood-cold { background: rgb(110, 141, 171); }
.tm-heat-mood-neutral { background: rgba(148, 163, 184, 0.5); }
.tm-heat-mood-none { background: transparent; }
/* 滚动条彻底隐藏（overflow-x:hidden 已物理禁止；此处双保险把 gutter
   也归零——Windows 上 overflow 容器即使无溢出也可能保留 scrollbar gutter） */
.tm-heat-scroll { scrollbar-width: none; }
.tm-heat-scroll::-webkit-scrollbar { display: none; height: 0; }
.tm-heat-scroll::-webkit-scrollbar-track { background: transparent; }
.tm-heat-scroll::-webkit-scrollbar-thumb { background: transparent; }
/* 底部脚注：说明文案 + 图例（GitHub 同款右下角布局） */
.tm-heat-footer { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; margin-top: 3px; }
.tm-heat-note { font-size: 10.5px; color: var(--muted); }
.tm-heat-legend { display: flex; align-items: center; gap: 4px; justify-content: flex-end; margin-left: auto; }
/* 图例在 .tm-heat-scroll 之外，拿不到 --tm-gh-cell（cqw 变量只在容器后代有效）；
   固定 10px 小方块，与网格格子语义解耦 */
.tm-heat-legend .tm-heat-cell { width: 10px; height: 10px; flex: 0 0 10px; }
.tm-heat-legend-label { font-size: 10.5px; color: var(--muted); margin: 0 2px; }
.tm-heat-legend-sep { width: 1px; height: 12px; margin: 0 6px; background: rgba(148, 163, 184, 0.35); }
.tm-heat-legend-mood { display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; color: var(--muted); position: relative; }
/* 图例里的心情示意色块：.tm-heat-mood 基类是 absolute + 百分比尺寸（为格子内色条设计），
   直接复用会逃逸出未定位的图例容器、按外层定位祖先（整页）计算尺寸——曾渲染出一条
   横贯页面的蓝色长条。这里收编为 static 固定小色块（暖=正、灰蓝=负） */
.tm-heat-legend-mood .tm-heat-mood {
  position: static; width: 10px; height: 5px; border-radius: 1.5px;
}

/* ---- 月报 ---- */
.tm-month-nav { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.tm-month-btn {
  border: 1px solid rgba(255, 255, 255, 0.8); background: rgba(255, 255, 255, 0.55); color: inherit;
  border-radius: 999px; min-width: 28px; height: 26px; cursor: pointer; font-size: 14px; line-height: 1;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9), 0 1px 3px rgba(96, 165, 250, 0.12);
  transition: transform 0.12s ease, background 0.12s ease;
}
.tm-month-btn:hover:not(:disabled) { background: rgba(255, 255, 255, 0.8); transform: scale(1.08); }
.tm-month-btn:disabled { opacity: 0.35; cursor: default; }
.tm-month-label { display: flex; align-items: center; gap: 6px; font-weight: 700; font-size: 13.5px; }
.tm-month-loading { color: var(--muted); }
.tm-month-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.tm-month-cell {
  display: flex; flex-direction: column; gap: 2px; padding: 10px 4px;
  border-radius: 10px; align-items: center;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.55) 0%, rgba(255, 255, 255, 0.32) 100%);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.85);
}
.tm-month-cell-value { font-size: 14.5px; font-weight: 750; font-variant-numeric: tabular-nums; }
.tm-month-cell-label { font-size: 11px; color: var(--muted); }
.tm-month-tone { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.tm-month-tone-label { font-size: 11.5px; color: var(--muted); }
.tm-month-tone-item {
  display: inline-flex; align-items: center; gap: 4px; font-size: 12px;
  padding: 3px 9px; border-radius: 999px;
  background: rgba(255, 255, 255, 0.55); border: 1px solid rgba(255, 255, 255, 0.75);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.9);
}
.tm-month-tone-count { font-size: 10.5px; color: var(--muted); }
.tm-month-tone-dot { display: inline-block; width: 8px; height: 8px; border-radius: 999px; }
/* 本月声音：玻璃引言卡（渐变顶边 + 大引号 + 衬线引文） */
.tm-month-voice { margin-top: 12px; }
.tm-month-voice-label {
  display: flex; align-items: center; gap: 6px;
  font-size: 11.5px; color: var(--muted); margin-bottom: 6px;
}
.tm-month-voice-text {
  position: relative; font-size: 13.5px; line-height: 1.8; padding: 14px 16px 12px 38px;
  border-radius: 0 12px 12px 0;
  background: linear-gradient(180deg, rgba(253, 250, 240, 0.72) 0%, rgba(250, 245, 232, 0.55) 100%);
  border: 1px solid rgba(231, 220, 195, 0.55);
  border-left: 3px solid rgb(245, 176, 77);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.8);
}
.tm-month-voice-text::before {
  content: "“"; position: absolute; left: 10px; top: 6px;
  font-size: 26px; line-height: 1; font-family: Georgia, "Times New Roman", serif;
  color: rgba(245, 176, 77, 0.75); pointer-events: none;
}
.tm-month-voice-empty { margin-top: 10px; font-size: 12px; color: var(--muted); }

/* ---- 时光页 · 暗色主题（放在浅色规则之后保证覆盖顺序）---- */
@media (prefers-color-scheme: dark) {
  /* ---- 时光页（1.1.0 精致化）暗色适配 ---- */
  .tm-hero-card {
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.6) 0%, rgba(30, 41, 59, 0.42) 100%);
    border-color: rgba(148, 163, 184, 0.18);
    box-shadow:
      inset 0 1px 0 rgba(148, 163, 184, 0.14),
      0 4px 14px rgba(245, 176, 77, 0.03),
      0 4px 14px rgba(96, 165, 250, 0.04);
  }
  .tm-hero-card::before {
    background: radial-gradient(240px 120px at 12% 0%, rgba(245, 176, 77, 0.08), transparent 70%);
  }
  .tm-hero-card::after {
    background: radial-gradient(240px 120px at 88% 100%, rgba(96, 165, 250, 0.08), transparent 70%);
  }
  .tm-hero-days-value {
    background: linear-gradient(180deg, #e8eef7 0%, #b3bfd2 100%);
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
  }
  .tm-hero-ring-inner {
    background: linear-gradient(180deg, rgba(15, 23, 42, 0.9) 0%, rgba(15, 23, 42, 0.75) 100%);
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.16), 0 1px 3px rgba(2, 6, 23, 0.5);
  }
  .tm-stat-cell {
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.55) 0%, rgba(30, 41, 59, 0.38) 100%);
    border-color: rgba(148, 163, 184, 0.16);
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.12);
  }
  .tm-stat-cell:hover { box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.18), 0 4px 12px rgba(2, 6, 23, 0.4); }
  .tm-ach { background: rgba(15, 23, 42, 0.4); border-color: rgba(148, 163, 184, 0.16); }
  .tm-ach:hover { box-shadow: 0 6px 16px rgba(2, 6, 23, 0.45); }
  .tm-ach-on {
    background:
      radial-gradient(140px 70px at 18% 0%, rgba(96, 165, 250, 0.12), transparent 70%),
      rgba(96, 165, 250, 0.04);
    border-color: rgba(96, 165, 250, 0.32);
  }
  .tm-ach:not(.tm-ach-on) .tm-glyph { color: rgba(203, 213, 225, 0.7); }
  /* 未解锁图标底座：暗色主题下同步压成中性灰（比亮色态略深一档） */
  .tm-ach:not(.tm-ach-on) .tm-ach-icon {
    background: radial-gradient(circle at 36% 30%, #9aa2b0 0%, #767e8c 58%, #5c6370 100%);
    box-shadow: inset 0 1px 1px rgba(226, 232, 240, 0.25), inset 0 -2px 5px rgba(2, 6, 23, 0.4), 0 1px 3px rgba(2, 6, 23, 0.3);
  }
  /* 热力图 GitHub 骨架暗色：标签提亮、空格底压暗（只动 lv0——
     覆盖 .tm-heat-cell 基类 background 会把 lv1~4 的档位色一起吞掉） */
  .tm-gh-month, .tm-gh-wd { color: rgba(148, 163, 184, 0.9); }
  .tm-heat-lv0 { background: rgba(51, 65, 85, 0.55); }
  .tm-heat-mood-neutral { background: rgba(148, 163, 184, 0.4); }
  .tm-month-btn {
    background: rgba(51, 65, 85, 0.55); border-color: rgba(148, 163, 184, 0.22);
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.16), 0 1px 3px rgba(2, 6, 23, 0.35);
  }
  .tm-month-btn:hover:not(:disabled) { background: rgba(51, 65, 85, 0.8); }
  .tm-month-cell {
    background: linear-gradient(180deg, rgba(30, 41, 59, 0.55) 0%, rgba(30, 41, 59, 0.38) 100%);
    border-color: rgba(148, 163, 184, 0.16);
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.12);
  }
  .tm-month-tone-item {
    background: rgba(30, 41, 59, 0.55); border-color: rgba(148, 163, 184, 0.18);
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.14);
  }
  .tm-month-voice-text {
    background: linear-gradient(180deg, rgba(38, 33, 24, 0.7) 0%, rgba(32, 28, 20, 0.6) 100%);
    border-color: rgba(180, 165, 130, 0.28);
    color: #d8d2c2;
    box-shadow: inset 0 1px 0 rgba(148, 163, 184, 0.08);
  }
  .tm-month-voice-text::before { color: rgba(245, 176, 77, 0.6); }
}

/* 时光页签图标：时钟（圆 + 指针） */
.tm-ico-moment { border: 1.5px solid currentColor; border-radius: 999px; }
.tm-ico-moment::before {
  content: ""; position: absolute; left: 50%; top: 50%;
  width: 1.5px; height: 4px; margin: -4px 0 0 -0.75px;
  background: currentColor; transform-origin: 50% 100%;
}
.tm-ico-moment::after {
  content: ""; position: absolute; left: 50%; top: 50%;
  width: 3px; height: 1.5px; margin: -0.75px 0 0 -0.75px;
  background: currentColor;
}

/* 靶心：日历选日模式按钮 */
.tm-ico-target { border: 1.5px solid currentColor; border-radius: 999px; }
.tm-ico-target::after {
  content: ""; position: absolute; left: 50%; top: 50%;
  width: 4px; height: 4px; margin: -2px 0 0 -2px;
  border-radius: 999px; background: currentColor;
}
`
