"""
PDF 图片合并脚本：将每页1张图的PDF，合并为每页N张图的新PDF。
用法：直接运行，修改 input_path 和 output_path 即可。
"""

import io
import os

import fitz  # PyMuPDF
from PIL import Image

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

INPUT_PATH = r"C:\Users\Administrator\Desktop\夸克扫描王_王辉.pdf"
OUTPUT_PATH = r"C:\Users\Administrator\Desktop\夸克扫描王_王辉_合并8图.pdf"

IMAGES_PER_PAGE = 8   # 每页几张图
COLS = 4              # 列数
ROWS = 2              # 行数
DPI = 200             # 提取分辨率
GAP = 8               # 图片间间隙（像素）

# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def main():
    if not os.path.exists(INPUT_PATH):
        print(f"[错误] 文件不存在: {INPUT_PATH}")
        return 1

    print(f"正在打开: {INPUT_PATH}")
    doc = fitz.open(INPUT_PATH)
    total = len(doc)
    print(f"总页数: {total}")

    # 逐页提取为 PIL Image
    images = []
    for i in range(total):
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=DPI)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
        print(f"  提取第 {i + 1}/{total} 页  尺寸: {img.size}")

    doc.close()

    # 计算单页画布尺寸（基于第一张图的比例缩放）
    sample = images[0]
    src_w, src_h = sample.size

    # 计算每张图在画布上的单元格尺寸（保持原比例缩放）
    # 画布宽度 = COLS * cell_w + (COLS+1)*GAP
    # 画布高度 = ROWS * cell_h + (ROWS+1)*GAP
    # 让 cell_w / cell_h ≈ src_w / src_h，取整后微调
    cell_w = (src_w * 2 // 3)  # 适当缩小，一张A4放8张
    cell_h = int(cell_w * src_h / src_w)

    page_w = COLS * cell_w + (COLS + 1) * GAP
    page_h = ROWS * cell_h + (ROWS + 1) * GAP

    print(f"\n拼图网格: {COLS}×{ROWS}  单元格: {cell_w}×{cell_h}  画布: {page_w}×{page_h}")

    # 分组拼接
    output_pages = []
    for g in range(0, len(images), IMAGES_PER_PAGE):
        group = images[g:g + IMAGES_PER_PAGE]
        canvas = Image.new("RGB", (page_w, page_h), "white")

        for idx, img in enumerate(group):
            row = idx // COLS
            col = idx % COLS
            x = GAP + col * (cell_w + GAP)
            y = GAP + row * (cell_h + GAP)

            # 等比例缩放至单元格内
            img_copy = img.copy()
            img_copy.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
            # 居中粘贴
            paste_x = x + (cell_w - img_copy.width) // 2
            paste_y = y + (cell_h - img_copy.height) // 2
            canvas.paste(img_copy, (paste_x, paste_y))

        output_pages.append(canvas)
        print(f"  合并第 {g // IMAGES_PER_PAGE + 1} 页 (含图 {g + 1}-{min(g + IMAGES_PER_PAGE, total)})")

    # 保存 PDF
    output_pages[0].save(
        OUTPUT_PATH,
        save_all=True,
        append_images=output_pages[1:],
        resolution=DPI,
    )

    print(f"\n[完成] 输出: {OUTPUT_PATH}")
    print(f"       原PDF {total} 页 → 新PDF {len(output_pages)} 页（每页{IMAGES_PER_PAGE}张图）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
