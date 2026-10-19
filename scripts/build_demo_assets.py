"""重新生成明确标记为演示数据的中文 PDF；仅开发时需要 reportlab==4.4.9。"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def build(destination, hours=None, edition=1):
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    title = "项目招标文件" if hours is None else "技术响应书"
    pdf = canvas.Canvas(str(destination), pagesize=A4, invariant=1)
    pdf.setTitle(title + " - 人工构造演示样本")
    pdf.setAuthor("bid_review demo")
    width, height = A4
    for page in range(1, 4):
        pdf.setFillColorRGB(.09, .17, .23)
        pdf.setFont("STSong-Light", 22)
        pdf.drawString(52, height - 76, title)
        pdf.setFont("STSong-Light", 11)
        pdf.setFillColorRGB(.38, .43, .47)
        pdf.drawString(52, height - 104, "城市服务平台运维项目 / 仅供产品体验，不用于实际投标")
        pdf.setStrokeColorRGB(.83, .86, .87)
        pdf.line(52, height - 124, width - 52, height - 124)
        pdf.setFillColorRGB(.12, .17, .21)
        pdf.setFont("STSong-Light", 12)
        if page == 1:
            lines = ["一、项目说明", "本项目采购城市服务平台一年的运维服务。",
                "招标文件是采购方提出的要求；技术响应书是服务商的承诺。",
                "本组文件、公司和人员均为人工构造的演示样例。"]
        elif page == 2:
            lines = ["二、服务响应与培训", "", "响应时限：接报后应在2小时内响应。" if hours is None
                else f"响应时限：我们承诺接报后在{hours}小时内响应。", "",
                "培训服务：应提供不少于2次操作培训。" if hours is None else "培训服务：我们承诺提供2次操作培训。",
                "", "本页条款须结合整份文件核对，不以单个数字替代人工判断。"]
        else:
            lines = ["三、驻场服务", "", "驻场人员：应安排不少于1名驻场工程师。" if hours is None
                else "驻场人员：我们承诺安排1名驻场工程师。", "",
                "服务期限为一年，具体内容以完整文件为准。",
                "校对说明：仅调整了文档排版，服务承诺未变。" if edition == 3 else "演示文件：请勿将此样例作为实际投标材料。"]
        for index, text in enumerate(lines):
            pdf.drawString(52, height - 168 - index * 32, text)
        pdf.setFont("STSong-Light", 10)
        pdf.setFillColorRGB(.45, .49, .52)
        pdf.drawString(52, 45, f"人工构造样例 / 第{edition}稿")
        pdf.drawRightString(width - 52, 45, f"第 {page} 页 / 共 3 页")
        pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent.parent / "app" / "demo_assets"
    directory.mkdir(exist_ok=True)
    for name, hours, edition in [("tender.pdf", None, 1), ("response-4h.pdf", 4, 1),
                                  ("response-2h.pdf", 2, 2), ("response-2h-v3.pdf", 2, 3)]:
        build(directory / name, hours, edition)
    print("Generated 4 clearly labelled synthetic Chinese PDF fixtures")
