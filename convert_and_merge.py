import os
from docx2pdf import convert
from pypdf import PdfWriter, PdfReader
import glob

# 获取当前目录
current_dir = os.getcwd()

# 获取所有docx文件
docx_files = glob.glob("*.docx")

print(f"找到 {len(docx_files)} 个Word文件:")
for f in docx_files:
    print(f"  - {f}")

# 转换每个docx为pdf
pdf_files = []
for docx_file in docx_files:
    pdf_file = docx_file.replace('.docx', '.pdf')
    
    print(f"正在转换: {docx_file} -> {pdf_file}")
    
    try:
        convert(docx_file, pdf_file, keep_active=True)
        pdf_files.append(pdf_file)
        print(f"  完成: {pdf_file}")
    except Exception as e:
        print(f"  转换失败: {e}")

# 合并所有pdf
print("\n开始合并PDF文件...")
writer = PdfWriter()

for pdf_file in pdf_files:
    print(f"  添加: {pdf_file}")
    reader = PdfReader(pdf_file)
    for page in reader.pages:
        writer.add_page(page)

# 保存合并后的PDF
output_file = "合并的自建笔记.pdf"
with open(output_file, "wb") as output:
    writer.write(output)

print(f"\n合并完成! 输出文件: {output_file}")
