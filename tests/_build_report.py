# -*- coding: utf-8 -*-
"""把 fig1/fig2/fig3 合成一份自包含的结论页(light 主题)。"""
import io
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "_chars_out")


def load(name):
    with io.open(os.path.join(OUT, name), "r", encoding="utf-8") as f:
        return f.read()


def sect(no, title, svg, caption):
    return (
        '<section class="card">\n'
        '  <h2><span class="no">%s</span>%s</h2>\n'
        '  <div class="fig">%s</div>\n'
        '  <p class="cap">%s</p>\n'
        '</section>\n' % (no, title, svg, caption)
    )


CSS = """
*{box-sizing:border-box}
body{margin:0;padding:32px 20px 64px;background:#F7F6F2;
     color:#2C2C2A;font:14px/1.7 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:20px;font-weight:500;margin:0 0 6px}
.sub{color:#5F5E5A;font-size:13px;margin:0 0 28px}
section.card{background:#fff;border:1px solid rgba(0,0,0,.08);border-radius:12px;
             padding:18px 20px 20px;margin:0 0 18px}
h2{font-size:15px;font-weight:500;margin:0 0 14px;display:flex;align-items:center;gap:10px}
h2 .no{display:inline-flex;align-items:center;justify-content:center;
       width:22px;height:22px;border-radius:6px;background:#EEEDFE;color:#534AB7;
       font-size:12px;font-weight:500;flex:none}
.fig{border:1px solid rgba(0,0,0,.06);border-radius:8px;overflow:hidden;background:#fff}
.fig svg{display:block}
p.cap{color:#5F5E5A;font-size:13px;margin:12px 0 0}
table{border-collapse:collapse;width:100%;font-size:13px;margin:6px 0 0}
th,td{border:1px solid rgba(0,0,0,.12);padding:6px 10px;text-align:left;vertical-align:top}
th{background:#F1EFE8;font-weight:500}
td.c{text-align:center}
code{font-family:ui-monospace,Consolas,monospace;font-size:12.5px;
     background:#F1EFE8;padding:1px 5px;border-radius:4px}
.ask{background:#FAEEDA;border:1px solid rgba(186,117,23,.35);border-radius:8px;
     padding:14px 16px;margin:14px 0 0;font-size:13px}
.ask b{font-weight:500;color:#854F0B}
.ok{color:#0F6E56}
"""

BODY = """
<div class="wrap">
<h1>中国三人象棋 —— 坐标体系 · 共线判据 · 过河接线</h1>
<p class="sub">全部结论基于 <code>board_135.json</code> 权威几何（135 点 / 51 线 / 6 条过河通道）逐点数值验证</p>

<section class="card">
  <h2><span class="no">1</span>行字母 + 图中数字 = 原图坐标系</h2>
  <table>
    <tr><th>方</th><th>行1（底线）</th><th>行2</th><th>行3</th><th>行4</th><th>行5（最内层）</th></tr>
    <tr><td>魏</td><td class="c">E</td><td class="c">D</td><td class="c">C</td><td class="c">B</td><td class="c">A</td></tr>
    <tr><td>吴</td><td class="c">O</td><td class="c">N</td><td class="c">M</td><td class="c">L</td><td class="c">K</td></tr>
    <tr><td>蜀</td><td class="c">J</td><td class="c">I</td><td class="c">H</td><td class="c">G</td><td class="c">F</td></tr>
  </table>
  <p class="cap">字母一律贴在各行的「列9」端（外端）。图中数字 <code>n</code> ↔ 引擎列 <code>10−n</code>，
  三方底边方向一致：图1＝车（列9）、图5＝帅（列5）、图9＝车（列1）。</p>
  <p class="cap">换算示例：吴 <code>O1</code> → 吴行1列9 ＝ <code>219</code>；吴 <code>O5</code> → <code>215</code>；
  吴 <code>O9</code> → <code>211</code>；吴 <code>M6</code> → 吴行3列4 ＝ <code>234</code>。</p>
</section>

__SEC1__

__SEC2__

<section class="card">
  <h2><span class="no">4</span>「数字和＝10 即共线」的物理实现</h2>
  <p class="cap">每方「行5 列k」出的过河方向，不管沿本方「列1」还是「列9」，都<b>精确命中</b>对方的「行5 列(10−k)」。
  全盘 3 方 × 9 列 × 2 侧 ＝ <b class="ok">54 条，逐条命中（容差 0.02 DXF 单位）</b>。</p>
  <table>
    <tr><th>出发</th><th>方向</th><th>命中</th><th>数字和</th></tr>
    <tr><td>魏 151（魏图9）</td><td>列9 方向</td><td>吴 259</td><td class="c">9+1=10</td></tr>
    <tr><td>魏 159（魏图1）</td><td>列1 方向</td><td>蜀 351</td><td class="c">1+9=10</td></tr>
    <tr><td>吴 259（吴图1）</td><td>列9 方向</td><td>魏 151</td><td class="c">1+9=10</td></tr>
    <tr><td>吴 251（吴图9）</td><td>列1 方向</td><td>蜀 159</td><td class="c">9+1=10</td></tr>
    <tr><td>吴 255（吴图5）</td><td>列1 / 列9 双向</td><td>魏 155 / 蜀 355</td><td class="c">5+5=10</td></tr>
  </table>
  <p class="cap">所以「只有底边 1 对对方 9、底边 9 对对方 1 是天然共线」这句，本质就是
  <b>k=1 与 k=9 这两条恰好落在网格自带的 −60°/0° 直线上</b>，其余 k 需要「列方向」延伸才能接上。</p>
</section>

<section class="card">
  <h2><span class="no">5</span>三条举例复核</h2>
  <table>
    <tr><th>老师给的例子</th><th>引擎编号</th><th>实际走线</th><th>结果</th></tr>
    <tr>
      <td>吴 <code>O1</code> 左车</td><td class="c">219<br>吴行1列9</td>
      <td><code>219 →229 →239 →249 →259 →351 →341 →331 →321 →311</code></td>
      <td class="ok">对上（吃蜀图9＝蜀列1 线上首个挡子）</td>
    </tr>
    <tr>
      <td>吴 <code>O5</code> 车兼顾两条线</td><td class="c">215<br>吴行1列5</td>
      <td><code>215 →225 →235 →245 →255</code> 然后分流<br>↳ 列5 向：<code>155</code>（魏图5）<br>↳ 列1 向：<code>355</code>（蜀图5）</td>
      <td class="ok">对上（5+5=10，正是您说的两条路同时兼顾）</td>
    </tr>
    <tr>
      <td>吴 <code>M6</code> 吃魏 4 线</td><td class="c">234<br>吴行3列4</td>
      <td><code>234 →244 →254 →（过河）→156 →146 →136 →126 →116</code></td>
      <td class="ok">对上（6+4=10 → 魏图4 线＝魏列6）</td>
    </tr>
  </table>
  <p class="cap">注意 <code>M6</code> 里的 M 是<b>行3</b>的横线、且带 29.2° 折角——它是干扰项；
  真正决定走向的是数字 6 对应的<b>列</b>方向。</p>
</section>

<section class="card">
  <h2><span class="no">6</span>待老师拍板</h2>
  <p class="cap">例③ 那段过河 <code>254 → 156</code>（含 <code>O1</code>、<code>O5</code> 的同类段）在 DXF 的
  51 条连线里<b>没有画线</b>：沿该线段采样，暗像素占比只有 8%–35%，而同长度的已知线是 96%–100%。</p>
  <div class="ask">
    <b>问题：</b>现在引擎的 <code>RAYS</code> 是靠「沿方向跨过空白区继续走」天然连通的，所以车/炮本来就打得过去。
    <br><br>
    ① 这算不算棋盘的设计意图——过河段是<b>网格构造自带的方向</b>（不画线也连通）？
    <br>
    ② 还是说原图漏画、需要在 <code>board_135.json</code> 里补上这 54 条显式连线？
    <br><br>
    我倾向 ①：因为 54/54 逐条精确命中，且命中点全部落在对方「行5」这一条构造线上，
    不像是巧合。若您认可，我就<b>保持几何与走法不动</b>，只在棋子/布局数据层工作。
  </div>
</section>
</div>
"""


def main():
    s1 = sect(2, "行线的折角：只有 E / J / O 是直线",
              load("fig1.svg"),
              "绿线＝吴行 M（行3）。行1（E/J/O）折角 0.00°；行2–5 在「列5（纵向中线）」处折角 "
              "16.31° / 29.20° / 39.41° / 47.58°（三方对称）。您的描述与数值完全一致。")
    s2 = sect(3, "过河接线：数字和恒为 10",
              load("fig2.svg"),
              "每方 9 个前沿点（行5列k）向就近一侧的对手过河，接到对方行5列(10−k)。"
              "同一结构在魏方、蜀方各旋转 120° 复制一份，合起来 54 条。")
    s3 = sect("3b", "例③ 吴 M6 的完整走线", load("fig3.svg"),
              "234 →244 →254（吴前沿）→ 过河 →156 →146 →136 →126 →116，"
              "吃这条线上第一个挡路的敌子。浅绿＝吴行M 横线（带折角，本走线不用它）。")

    html = ("<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n"
            "<title>三人象棋 · 坐标体系与共线判据</title>\n<style>%s</style>\n</head>\n<body>\n"
            % CSS)
    body = BODY.replace("__SEC1__", s1).replace("__SEC2__", s2 + "\n" + s3)
    html += body + "\n</body>\n</html>\n"

    out = os.path.join(OUT, "结论_坐标体系与共线.html")
    with io.open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print("已写", out, len(html.encode("utf-8")), "字节")


if __name__ == "__main__":
    main()
