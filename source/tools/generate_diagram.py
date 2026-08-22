#!/usr/bin/env python3
"""
generate_diagram.py — สร้าง Diagram จากโค้ดโปรแกรมอัตโนมัติ

ใช้ ast วิเคราะห์แต่ละไฟล์ .py แล้วสร้าง Mermaid ที่แสดง:
  - Classes และ public functions ในแต่ละไฟล์
  - ความสัมพันธ์ (import) ระหว่างไฟล์

ใช้งาน:    python tools/generate_diagram.py
ผลลัพธ์:   tools/diagram_auto.mmd
           tools/diagram_auto.html
"""

import ast
import sys
from pathlib import Path
from datetime import datetime

# ── Paths ───────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent.parent   # โฟลเดอร์โปรแกรมหลัก
TOOLS_DIR   = Path(__file__).parent          # โฟลเดอร์ tools/ (ไฟล์นี้อยู่ที่นี่)

# ── ไฟล์ที่ต้องการวิเคราะห์ (เรียงตามลำดับ dependency) ──────
TARGET_FILES = [
    "config.py",
    "widgets.py",
    "database.py",
    "parser.py",
    "pages.py",
    "app.py",
]

# ── สีประจำแต่ละไฟล์ใน diagram ──────────────────────────────
FILE_COLORS = {
    "app.py":      "#1a3a2a",
    "pages.py":    "#2a1a3a",
    "database.py": "#1a2a3a",
    "parser.py":   "#3a2a1a",
    "config.py":   "#1e3a5f",
    "widgets.py":  "#2a2a1a",
}


# ════════════════════════════════════════════════════════════
# ANALYSIS
# ════════════════════════════════════════════════════════════

def node_id(fname: str) -> str:
    """แปลงชื่อไฟล์เป็น Mermaid node ID (ห้ามมี . ใน ID)"""
    return fname.replace(".", "_")


def analyze_file(path: Path) -> dict:
    """
    วิเคราะห์ไฟล์ Python ด้วย ast
    คืน dict: classes, functions (public top-level), local_imports
    """
    try:
        src  = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
    except Exception as e:
        return {"error": str(e), "classes": [], "functions": [], "local_imports": []}

    # Classes ทั้งหมดในไฟล์
    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]

    # เฉพาะ top-level public functions (ไม่ขึ้นต้นด้วย _)
    functions = [
        n.name for n in ast.iter_child_nodes(tree)
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    ]

    # imports ที่อ้างถึงไฟล์อื่นในโปรเจคเดียวกัน
    project_stems = {Path(f).stem for f in TARGET_FILES}
    local_imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in project_stems:
            local_imports.add(node.module + ".py")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in project_stems:
                    local_imports.add(alias.name + ".py")

    return {
        "classes":       classes,
        "functions":     functions,
        "local_imports": sorted(local_imports),
    }


# ════════════════════════════════════════════════════════════
# MERMAID BUILDER
# ════════════════════════════════════════════════════════════

def build_mermaid(file_data: dict) -> str:
    """สร้าง Mermaid flowchart จาก file_data"""
    lines = ["flowchart LR"]

    # ── Node ──────────────────────────────────────────
    for fname, info in file_data.items():
        nid   = node_id(fname)
        parts = [f"**{fname}**"]

        if info.get("classes"):
            parts.append("─────")
            for c in info["classes"][:4]:
                parts.append(f"📦 {c}")
            if len(info["classes"]) > 4:
                parts.append(f"   +{len(info['classes'])-4} more")

        if info.get("functions"):
            parts.append("─────")
            for f in info["functions"][:5]:
                parts.append(f"⚙ {f}()")
            if len(info["functions"]) > 5:
                parts.append(f"   +{len(info['functions'])-5} more")

        label = "\\n".join(parts)
        lines.append(f'    {nid}["{label}"]')

    lines.append("")

    # ── Edges (import dependency) ────────────────────
    for fname, info in file_data.items():
        for imp in info.get("local_imports", []):
            if imp in file_data:
                lines.append(f"    {node_id(fname)} --> {node_id(imp)}")

    lines.append("")

    # ── Styles ──────────────────────────────────────
    for fname, color in FILE_COLORS.items():
        if fname in file_data:
            lines.append(
                f"    style {node_id(fname)} fill:{color},color:#fff,stroke:#aaa"
            )

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════
# HTML TEMPLATE
# ════════════════════════════════════════════════════════════

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <title>KM Meter — Auto Diagram</title>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ background:#1a1a2e; color:#e0e0e0;
           font-family:'Segoe UI',sans-serif;
           display:flex; flex-direction:column; align-items:center;
           padding:24px 16px; min-height:100vh; margin:0; }}
    h1   {{ font-size:1.3rem; color:#a0c4ff; margin-bottom:4px; }}
    p.sub {{ font-size:0.8rem; color:#666; margin-bottom:12px; }}
    .zoom-bar {{ display:flex; align-items:center; gap:8px; margin-bottom:12px;
                 background:#16213e; border:1px solid #2a3a5a;
                 border-radius:8px; padding:6px 12px; }}
    .zoom-bar button {{ width:32px; height:32px; border:none; border-radius:6px;
                        background:#2a3a5a; color:#e0e0e0; font-size:1.1rem; cursor:pointer; }}
    .zoom-bar button:hover {{ background:#3a5a8a; }}
    .zoom-bar span {{ min-width:52px; text-align:center; font-size:0.85rem; color:#a0c4ff; }}
    .wrap {{ background:#16213e; border-radius:12px; width:100%;
             height:calc(100vh - 160px); min-height:500px;
             overflow:auto; cursor:grab;
             box-shadow:0 4px 24px rgba(0,0,0,0.5); }}
    .wrap:active {{ cursor:grabbing; }}
    .inner {{ display:inline-block; padding:32px;
              transform-origin:top left; transition:transform 0.15s ease; }}

    /* ═══════ PRINT STYLES (A4 Landscape) ═══════ */
    @page {{ size: A4 landscape; margin: 10mm; }}
    @media print {{
      * {{ box-sizing: border-box; }}
      body {{ background: white; color: black; padding: 0; margin: 0; }}
      h1 {{ font-size: 1.1rem; color: black; margin: 8px 0 2px 0; }}
      p.sub {{ font-size: 0.7rem; color: #333; margin-bottom: 8px; }}
      .zoom-bar {{ display: none !important; }}
      .wrap {{ background: white; border-radius: 0; width: 100%; height: auto;
               overflow: visible; cursor: auto; box-shadow: none;
               border: 1px solid #ccc; }}
      .wrap:active {{ cursor: auto; }}
      .inner {{ display: block; padding: 0; transform: none !important;
                transform-origin: inherit; transition: none; }}
      .mermaid svg {{ max-width: 100%; height: auto; }}
    }}
  </style>
</head>
<body>
  <h1>KM Meter Reader — Auto-Generated Diagram</h1>
  <p class="sub">สร้างเมื่อ: {timestamp} &nbsp;·&nbsp; รัน: python tools/generate_diagram.py</p>

  <div class="zoom-bar">
    <button id="btn-out">−</button>
    <span   id="zoom-lbl">150%</span>
    <button id="btn-in">+</button>
    <button id="btn-fit" style="width:auto;padding:0 10px;font-size:0.8rem;">Reset</button>
  </div>

  <div class="wrap" id="wrap">
    <div class="inner" id="inner">
      <div class="mermaid">
{mermaid}
      </div>
    </div>
  </div>

  <script>
    mermaid.initialize({{
      startOnLoad: true, theme: 'dark', fontSize: 18,
      flowchart: {{ nodeSpacing: 55, rankSpacing: 80, padding: 20 }}
    }});

    let scale = 1.5;
    const STEP = 0.25, MIN = 0.2, MAX = 10;
    const inner = document.getElementById('inner');
    const lbl   = document.getElementById('zoom-lbl');

    function applyZoom() {{
      inner.style.transform = `scale(${{scale}})`;
      lbl.textContent = Math.round(scale * 100) + '%';
    }}
    window.addEventListener('load', () => setTimeout(applyZoom, 700));

    document.getElementById('btn-in').onclick  = () => {{ scale = Math.min(MAX, +(scale+STEP).toFixed(2)); applyZoom(); }};
    document.getElementById('btn-out').onclick = () => {{ scale = Math.max(MIN, +(scale-STEP).toFixed(2)); applyZoom(); }};
    document.getElementById('btn-fit').onclick = () => {{ scale = 1; applyZoom(); }};

    document.getElementById('wrap').addEventListener('wheel', e => {{
      if (!e.ctrlKey) return;
      e.preventDefault();
      scale = e.deltaY < 0
        ? Math.min(MAX, +(scale+STEP).toFixed(2))
        : Math.max(MIN, +(scale-STEP).toFixed(2));
      applyZoom();
    }}, {{ passive: false }});

    /* ═══════ PRINT TIPS ═══════ */
    console.log('💡 ในการพิมพ์:');
    console.log('   1. Ctrl+P (หรือ Cmd+P) เพื่อเปิด Print Dialog');
    console.log('   2. ตั้ง: Orientation = Landscape');
    console.log('   3. ตั้ง: Paper Size = A4');
    console.log('   4. Background Graphics = ON (สำหรับสี)');
    console.log('   5. Margins = Minimal');
  </script>
</body>
</html>
"""


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  generate_diagram.py — KM Meter Auto Diagram")
    print("=" * 55)

    # ── วิเคราะห์ไฟล์ ─────────────────────────────────
    print("\n🔍 วิเคราะห์ไฟล์โปรแกรม...")
    file_data = {}
    for fname in TARGET_FILES:
        fpath = PROJECT_DIR / fname
        if fpath.exists():
            info = analyze_file(fpath)
            file_data[fname] = info
            c_str = ", ".join(info["classes"]) or "—"
            f_str = ", ".join(info["functions"][:4]) or "—"
            print(f"  ✓  {fname:15s}  classes: [{c_str}]")
            print(f"  {'':17s}  funcs  : [{f_str}]")
        else:
            print(f"  ✗  {fname:15s}  (ไม่พบไฟล์)")

    # ── สร้าง Mermaid ─────────────────────────────────
    print("\n📝 สร้าง Mermaid diagram...")
    mmd_content = build_mermaid(file_data)

    # ── บันทึก .mmd ───────────────────────────────────
    mmd_path = TOOLS_DIR / "diagram_auto.mmd"
    mmd_path.write_text(mmd_content, encoding="utf-8")
    print(f"  ✓  บันทึก {mmd_path.name}")

    # ── บันทึก .html ──────────────────────────────────
    html_content = HTML_TEMPLATE.format(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        mermaid=mmd_content,
    )
    html_path = TOOLS_DIR / "diagram_auto.html"
    html_path.write_text(html_content, encoding="utf-8")
    print(f"  ✓  บันทึก {html_path.name}")

    print(f"\n✅ เสร็จแล้ว!")
    print(f"   เปิดใน browser: {html_path}")
    print(f"   (diagram มือ:  {TOOLS_DIR / 'diagram.html'})")
