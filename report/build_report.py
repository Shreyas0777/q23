"""Build the Q23 report from the supplied university DOCX template."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "Report_Template.docx"
OUTPUT = ROOT / "23_Q23_Report.docx"
FLOWCHART = ROOT / "report" / "figure_3_1_flowchart.png"
BASIC_SCREENSHOT = ROOT / "evidence" / "basic_execution.png.png"
SPILL_SCREENSHOT = ROOT / "evidence" / "spill_reload.png.png"
PYTEST_SCREENSHOT = ROOT / "evidence" / "pytest_results.png.png"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))
from code_generator import CodeGenerator, TACError, generate_code, parse_tac  # noqa: E402
from test_codegen import execute_assembly, execute_tac  # noqa: E402


def set_cell_shading(cell, fill="E7E6E6"):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def repeat_table_header(row):
    tr_pr = row._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    tr_pr.append(header)


def keep_row_together(row):
    row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))


def page_field(paragraph, fmt="PAGE"):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = f" {fmt} "
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    result = OxmlElement("w:t"); result.text = "1"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    for item in (begin, instr, separate, result, end):
        run._r.append(item)


def set_page_number_format(section, fmt, start=1):
    sect_pr = section._sectPr
    node = sect_pr.find(qn("w:pgNumType"))
    if node is None:
        node = OxmlElement("w:pgNumType")
        sect_pr.append(node)
    node.set(qn("w:fmt"), fmt)
    node.set(qn("w:start"), str(start))


def set_page_geometry(section):
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = Inches(1.5)
    section.right_margin = Inches(1)
    section.top_margin = Inches(1)
    section.bottom_margin = Inches(1)
    section.header_distance = Inches(0.5)
    section.footer_distance = Inches(0.5)


def set_font(run, name="Times New Roman", size=12, bold=None, italic=None):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor(0, 0, 0)
    if bold is not None: run.bold = bold
    if italic is not None: run.italic = italic


def clear_body(doc):
    body = doc._element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def add_par(doc, text="", style=None, align=None, size=12, bold=False, italic=False,
            font="Times New Roman", after=6, spacing=1.5, keep=False):
    p = doc.add_paragraph(style=style)
    if align is not None: p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.line_spacing = spacing
    p.paragraph_format.keep_together = True
    if keep: p.paragraph_format.keep_with_next = True
    if text:
        r = p.add_run(text)
        set_font(r, font, size, bold=bold, italic=italic)
    return p


def heading(doc, text, level=1):
    style = "Heading 1" if level == 1 else "Heading 2"
    p = doc.add_paragraph(style=style)
    p.paragraph_format.keep_with_next = True
    p.paragraph_format.space_before = Pt(3 if level == 1 else 1)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_font(r, size=14 if level == 1 else 12, bold=True, italic=(level == 2 and False))
    return p


def add_table(doc, headers, rows, widths=None, font_size=10, header_fill="E7E6E6"):
    table = doc.add_table(rows=1, cols=len(headers))
    table.autofit = False
    repeat_table_header(table.rows[0])
    for j, value in enumerate(headers):
        cell = table.rows[0].cells[j]
        cell.text = str(value)
        set_cell_shading(cell, header_fill)
    for row_data in rows:
        row = table.add_row()
        keep_row_together(row)
        for j, value in enumerate(row_data):
            row.cells[j].text = str(value)
    for row in table.rows:
        for j, cell in enumerate(row.cells):
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            if widths and j < len(widths): cell.width = Inches(widths[j])
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(1)
                p.paragraph_format.line_spacing = 1.0
                for run in p.runs:
                    set_font(run, size=font_size, bold=(row is table.rows[0]))
            tc_pr = cell._tc.get_or_add_tcPr()
            borders = tc_pr.first_child_found_in("w:tcBorders")
            if borders is None:
                borders = OxmlElement("w:tcBorders")
                tc_pr.append(borders)
            for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
                tag = "w:" + edge
                element = borders.find(qn(tag))
                if element is None:
                    element = OxmlElement(tag); borders.append(element)
                element.set(qn("w:val"), "single")
                element.set(qn("w:sz"), "4")
                element.set(qn("w:color"), "D9D9D9")
    return table


def add_page_num(section, roman=False):
    section.footer.is_linked_to_previous = False
    p = section.footer.paragraphs[0]
    p.clear()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(0)
    page_field(p)
    for run in p.runs: set_font(run, size=10)
    if roman:
        # Word handles format via section properties, not field text.
        set_page_number_format(section, "lowerRoman", 1)
    else:
        set_page_number_format(section, "decimal", 1)


def set_header(section, title="Q23 Three Register Code Generator", roll="23", visible=True):
    section.header.is_linked_to_previous = False
    p = section.header.paragraphs[0]
    p.clear()
    if visible:
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.line_spacing = 1.0
        p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(title)
        set_font(r, size=9)
        p.paragraph_format.tab_stops.add_tab_stop(Inches(5.7), WD_TAB_ALIGNMENT.RIGHT)
        r2 = p.add_run("\t" + roll)
        set_font(r2, size=9)
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single"); bottom.set(qn("w:sz"), "4"); bottom.set(qn("w:space"), "2"); bottom.set(qn("w:color"), "A6A6A6")
        pBdr.append(bottom); pPr.append(pBdr)


def add_code(doc, filename, source):
    p = add_par(doc, f"File: {filename}", size=10, bold=True, after=3, spacing=1.0, keep=True)
    for line_no, line in enumerate(source.splitlines(), 1):
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.1)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        r = p.add_run(f"{line_no:04d}  {line}")
        set_font(r, "Courier New", 10)


def add_code_box(doc, source):
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    cell.text = ""
    for line_no, line in enumerate(source.splitlines(), 1):
        p = cell.paragraphs[0] if line_no == 1 else cell.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.keep_together = True
        set_font(p.add_run(f"{line_no:02d}  {line}"), "Courier New", 10)
    for row in table.rows:
        keep_row_together(row)
        for cell in row.cells:
            tc_pr = cell._tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                item = OxmlElement(f"w:{edge}")
                item.set(qn("w:val"), "single"); item.set(qn("w:sz"), "5"); item.set(qn("w:color"), "808080")
                borders.append(item)
            tc_pr.append(borders)


def add_screenshot_figure(doc, path, caption, width=5.4):
    """Embed an evidence PNG unchanged and add its numbered caption."""
    if not path.is_file():
        raise FileNotFoundError(f"Required screenshot not found: {path}")
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    p.add_run().add_picture(str(path), width=Inches(width))
    caption_p = add_par(doc, caption, align=WD_ALIGN_PARAGRAPH.CENTER,
                        size=10, bold=True, after=4, spacing=1.0)
    caption_p.paragraph_format.keep_together = True


def create_flowchart(path=FLOWCHART):
    """Draw a true flowchart for the code-generation stages (300 dpi)."""
    width, height = 1800, 1120
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    bold_path = Path("C:/Windows/Fonts/arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 28)
    bold = ImageFont.truetype(str(bold_path), 30)
    small = ImageFont.truetype(str(font_path), 24)
    ink, fill = "#111111", "#F2F2F2"

    def centered(text, box, use_font=font):
        x1, y1, x2, y2 = box
        lines = text.split("\n")
        heights = [draw.textbbox((0, 0), line, font=use_font)[3] for line in lines]
        y = (y1 + y2 - sum(heights) - 8 * (len(lines)-1)) / 2
        for line, line_h in zip(lines, heights):
            tw = draw.textbbox((0, 0), line, font=use_font)[2]
            draw.text(((x1+x2-tw)/2, y), line, font=use_font, fill=ink)
            y += line_h + 8

    def box(rect, text, shape="rect", use_font=font):
        if shape == "round": draw.rounded_rectangle(rect, radius=45, fill=fill, outline=ink, width=4)
        elif shape == "io":
            x1,y1,x2,y2=rect; slant=45
            draw.polygon([(x1+slant,y1),(x2,y1),(x2-slant,y2),(x1,y2)], fill=fill, outline=ink)
            draw.line([(x1+slant,y1),(x2,y1),(x2-slant,y2),(x1,y2),(x1+slant,y1)], fill=ink, width=4)
        elif shape == "diamond":
            x1,y1,x2,y2=rect
            draw.polygon([((x1+x2)//2,y1),(x2,(y1+y2)//2),((x1+x2)//2,y2),(x1,(y1+y2)//2)], fill=fill, outline=ink)
            draw.line([((x1+x2)//2,y1),(x2,(y1+y2)//2),((x1+x2)//2,y2),(x1,(y1+y2)//2),((x1+x2)//2,y1)], fill=ink, width=4)
        else: draw.rectangle(rect, fill=fill, outline=ink, width=4)
        centered(text, rect, use_font)

    def arrow(points, label=None, label_at=None):
        draw.line(points, fill=ink, width=4, joint="curve")
        x1,y1=points[-2]; x2,y2=points[-1]
        if abs(x2-x1) > abs(y2-y1):
            s=1 if x2>x1 else -1
            head=[(x2,y2),(x2-18*s,y2-12),(x2-18*s,y2+12)]
        else:
            s=1 if y2>y1 else -1
            head=[(x2,y2),(x2-12,y2-18*s),(x2+12,y2-18*s)]
        draw.polygon(head, fill=ink)
        if label and label_at:
            draw.text(label_at, label, font=small, fill=ink)

    # Primary path through parsing and analysis.
    box((45,105,250,205), "START", "round", bold)
    box((315,95,600,215), "TAC INPUT", "io", bold)
    box((665,95,930,215), "PARSE AND\nVALIDATE", "rect", bold)
    box((995,95,1280,215), "NEXT-USE\nANALYSIS", "rect", bold)
    box((1350,95,1745,215), "getReg()\nchoose a register", "rect", bold)
    arrow([(250,155),(315,155)]); arrow([(600,155),(665,155)])
    arrow([(930,155),(995,155)]); arrow([(1280,155),(1350,155)])

    box((1395,315,1700,455), "REGISTER\nAVAILABLE?", "diamond", bold)
    arrow([(1548,215),(1548,315)])
    box((1405,535,1745,665), "SPILL OR REUSE\nVICTIM", "rect", bold)
    box((990,535,1320,665), "ALLOCATE IN\nR0, R1 OR R2", "rect", bold)
    arrow([(1548,455),(1548,535)], "NO", (1560,475))
    arrow([(1400,385),(1280,385),(1280,535)], "YES", (1300,350))
    arrow([(1405,600),(1320,600)])

    box((610,535,910,665), "OPERAND\nALREADY IN REG?", "diamond", bold)
    arrow([(990,600),(910,600)])
    box((230,535,520,665), "LOAD INPUT OR\nRELOAD SPILLED VALUE", "rect", small)
    arrow([(610,600),(520,600)], "NO", (550,560))
    box((230,800,520,925), "GENERATE\nASSEMBLY", "rect", bold)
    arrow([(760,665),(760,740),(520,740),(520,860)], "YES - REUSE", (580,715))
    arrow([(375,665),(375,800)])

    box((610,800,920,925), "MORE TAC?", "diamond", bold)
    arrow([(520,860),(610,860)])
    box((1040,800,1370,925), "ASSEMBLY\nOUTPUT", "io", bold)
    box((1500,810,1730,915), "END", "round", bold)
    arrow([(920,860),(1040,860)], "NO", (955,825))
    arrow([(1370,860),(1500,860)])
    arrow([(760,800),(760,735),(1745,735),(1745,270),(1548,270)], "YES - NEXT INSTRUCTION", (1050,700))

    image.save(path, dpi=(300,300))
    return path


def getreg_source_snippet():
    source = (ROOT / "src" / "code_generator.py").read_text(encoding="utf-8").splitlines()
    start = next(i for i, line in enumerate(source) if line.startswith("    def getReg"))
    end = next(i for i in range(start + 1, len(source)) if source[i].startswith("    def load"))
    snippet = [line.rstrip() for line in source[start:end] if line.strip()]
    if len(snippet) > 25:
        raise ValueError(f"getReg code excerpt is {len(snippet)} lines; maximum is 25")
    return "\n".join(snippet)


def _format_result(env, printed, returned, watched):
    parts = [f"{name}={env[name]}" for name in watched if name in env]
    if printed: parts.append("P=" + ",".join(map(str, printed)))
    if returned is not None: parts.append(f"R={returned}")
    return "; ".join(parts) if parts else "HALT"


def build_test_table_rows():
    """Run each report case through both interpreters; never hard-code actuals."""
    cases = [
        ("TC01", "<empty>", "", {}, (), ()),
        ("TC02", "x=42", "x = 42", {}, (), ("x",)),
        ("TC03", "a=7,b=5; x=a+b", "x = a + b", {"a":7,"b":5}, (), ("x",)),
        ("TC04", "a=20,b=6; x=a-b", "x = a - b", {"a":20,"b":6}, (), ("x",)),
        ("TC05", "a=19; x=a/2", "x = a / 2", {"a":19}, (), ("x",)),
        ("TC06", "read a; x=a+2; print/return x",
         "read a\nx = a + 2\nprint x\nreturn x", {}, (21,), ("x",)),
        ("TC07", "a=8; true branch",
         "if a >= 5 goto high\nx = 1\ngoto done\nhigh:\nx = 2\ndone:\nprint x\nreturn x",
         {"a":8}, (), ("x",)),
        ("TC08", "a=2; false branch",
         "if a >= 5 goto high\nx = 1\ngoto done\nhigh:\nx = 2\ndone:\nprint x\nreturn x",
         {"a":2}, (), ("x",)),
        ("TC09", "pressure; a..f=1..6",
         "t1=a+b\nt2=c+d\nt3=e+f\nt4=t1*t2\nx=t3+t4",
         {"a":1,"b":2,"c":3,"d":4,"e":5,"f":6}, (), ("x",)),
    ]
    rows = []
    for tc, label, tac, initial, inputs, watched in cases:
        expected_env, expected_print, expected_return = execute_tac(tac, initial, inputs)
        generator = CodeGenerator(parse_tac(tac))
        assembly = generator.generate()
        actual_env, actual_print, actual_return = execute_assembly(assembly, initial, inputs)
        expected = _format_result(expected_env, expected_print, expected_return, watched)
        actual = _format_result(actual_env, actual_print, actual_return, watched)
        passed = expected_env.get("x") == actual_env.get("x") and expected_print == actual_print and expected_return == actual_return
        if tc == "TC01":
            expected, actual, passed = "HALT", assembly, assembly == "HALT"
        if tc == "TC09":
            expected += "; at least one spill and reload"
            actual += f"; spills={generator.spill_count}, reloads={generator.reload_count}"
            passed = passed and generator.spill_count > 0 and generator.reload_count > 0
        rows.append((tc, label, expected, actual, "PASS" if passed else "FAIL"))

    register_tac = "t1=a+b\nt2=c+d\nt3=e+f\nx=t1+t2\ny=x+t3"
    assembly = generate_code(register_tac)
    registers = sorted(set(re.findall(r"\bR\d+\b", assembly)))
    register_pass = bool(registers) and set(registers) <= {"R0","R1","R2"}
    rows.append(("TC10", "pressure TAC; register limit",
                 "Only R0, R1, R2",
                 ", ".join(registers), "PASS" if register_pass else "FAIL"))

    for tc, source in (("TC11", "invalid: x ="), ("TC12", "goto missing")):
        try:
            parse_tac(source)
            actual, passed = "Accepted", False
        except TACError as error:
            actual, passed = str(error), True
        rows.append((tc, source, "Reject invalid TAC", actual, "PASS" if passed else "FAIL"))
    if any(row[-1] != "PASS" for row in rows):
        raise AssertionError(f"Report test table contains a failed case: {rows}")
    return rows


def build_ai_history_rows():
    """Concise paraphrases of documented project stages; these are not quotations."""
    return [
        ("Assignment review", "ChatGPT", "Asked for help matching roll number 23 to the assigned question and understanding Q23.",
         "Explained that the task is TAC-to-assembly-like translation with three registers and getReg().",
         "Confirmed Q23 and clarified the assignment goal."),
        ("Language and setup", "ChatGPT", "Asked about choosing a language/editor and setting up folders with VS Code and PowerShell.",
         "Discussed Python 3, VS Code, and a simple src/tests/samples project layout.",
         "Used Python 3 and organized work in the Q23 project folder."),
        ("Implementation plan", "ChatGPT", "Asked for a beginner-friendly plan for parsing, allocation, spills, and testing.",
         "Explained the development stages and key compiler concepts.",
         "Used the plan to guide the implementation request."),
        ("Project implementation", "Codex (GPT-6)", "Requested a full project build after checking the existing code and tests.",
         "Modified code, tests, guides, and report files; ran Python and test commands.",
         "Reviewed the generated work and disclosed AI assistance; AI-generated code is not claimed as independent authorship."),
        ("Testing and debugging", "ChatGPT and Codex", "Asked for help with test failures, slow analysis, and spill/reload problems.",
         "ChatGPT supported troubleshooting; Codex changed the local implementation and executed tests.",
         "Reviewed fixes and reran the suite; the recorded final run was 22 passed with one warning."),
        ("Report revisions", "ChatGPT and Codex", "Requested reviews of report versions, template formatting, captions, and page limits.",
         "ChatGPT gave review and revision guidance; Codex edited and regenerated the DOCX and PDF.",
         "Checked outputs and requested corrections to keep the report accurate and within five main pages."),
        ("Screenshots and viva", "ChatGPT and Codex", "Asked for authentic screenshot evidence and study material for the viva.",
         "ChatGPT helped with guidance; Codex inserted user-supplied screenshots and prepared learning/viva files.",
         "Supplied genuine terminal captures and reviewed their placement; screenshot contents were not recreated."),
    ]


def report():
    doc = Document(TEMPLATE)
    clear_body(doc)
    # Use the template section properties and styles; create front matter and report sections.
    title_section = doc.sections[0]
    set_page_geometry(title_section)
    title_section.different_first_page_header_footer = True
    set_header(title_section, visible=False)
    title_section.footer.is_linked_to_previous = False
    title_section.footer.paragraphs[0].clear()

    # Title page
    add_par(doc, "DAYANANDA SAGAR UNIVERSITY", align=WD_ALIGN_PARAGRAPH.CENTER, size=16, bold=True, after=3, spacing=1.0)
    add_par(doc, "School of Engineering", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, after=0, spacing=1.0)
    add_par(doc, "Department of Computer Science and Engineering", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, after=14, spacing=1.0)
    add_par(doc, "Course: Automata Theory and Compiler Design", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=1, spacing=1.0)
    add_par(doc, "Course Code: 25CS3506", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=18, spacing=1.0)
    add_par(doc, "A REPORT ON", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, bold=True, after=6, spacing=1.0)
    add_par(doc, "AI-POWERED PROGRAMMING / IMPLEMENTATION ASSIGNMENT", align=WD_ALIGN_PARAGRAPH.CENTER, size=13, bold=True, after=14, spacing=1.0)
    add_par(doc, "Question No.: Q23", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, bold=True, after=3, spacing=1.0)
    add_par(doc, "Title: Three Register TAC Code Generator", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, after=20, spacing=1.0)
    add_par(doc, "Submitted by", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, bold=True, after=2, spacing=1.0)
    add_par(doc, "Name: Shreyas S Harapanahalli    Roll No.: 23    USN: ENG24CS0227", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=2, spacing=1.0)
    add_par(doc, "Semester / Section: 5th Semester / D    Programme: B.Tech. CSE", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=10, spacing=1.0)
    add_par(doc, "Submitted to: [Faculty Name], [Designation]", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=2, spacing=1.0)
    add_par(doc, "Department: Computer Science and Engineering", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=2, spacing=1.0)
    add_par(doc, "Date of submission: [DD / MM / YYYY]", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, after=24, spacing=1.0)
    add_par(doc, "2026-27 - ODD", align=WD_ALIGN_PARAGRAPH.CENTER, size=12, bold=True, after=2, spacing=1.0)
    add_par(doc, "Bengaluru South District, Karnataka 562112", align=WD_ALIGN_PARAGRAPH.CENTER, size=11, italic=True, after=0, spacing=1.0)

    front = doc.add_section(WD_SECTION.NEW_PAGE)
    set_page_geometry(front); front.different_first_page_header_footer = False
    set_header(front, roll="23", visible=True); add_page_num(front, roman=True)
    heading(doc, "DECLARATION", 1)
    add_par(doc, "I, Shreyas S Harapanahalli, USN ENG24CS0227, Roll No. 23, of 5th Semester, Section D, Department of Computer Science and Engineering, Dayananda Sagar University, submit this report on Question Q23, titled “Three Register TAC Code Generator,” for Automata Theory and Compiler Design during academic year 2026-27. This report records the implementation, testing, and AI assistance used in preparing the project. The code and report were developed with AI assistance, which is disclosed in Chapter 7 and Appendix B. I will verify, understand, and adapt the implementation in accordance with the course rules before signing this declaration.")
    add_par(doc, "I declare that the personal details and signature below will be completed by me and that I will not sign this declaration until it truthfully reflects my contribution and understanding.")
    add_par(doc, "Place: [City]                                      Signature: ____________________", size=11, after=1)
    add_par(doc, "Date: [DD / MM / YYYY]                         Shreyas S Harapanahalli / ENG24CS0227 / 23", size=11)

    doc.add_page_break()
    heading(doc, "ABSTRACT", 1)
    abstract = ("This project translates three-address code (TAC) into assembly-like instructions for a target machine with three registers, R0, R1, and R2. A Python 3 implementation parses assignments, arithmetic, input/output, labels, branches, and returns; checks branch labels; indexes sparse next-use events; and uses register and address descriptors. Its getReg routine selects a free register or evicts a value, writing a spill only when memory is stale, while active operands are pinned. Values read before a definition are recognized as already valid in input memory. The program distinguishes ordinary loads, genuine spill/reload events, and boundary flushes. Twenty-two automated tests cover input/output, returns, both branch paths, register pressure, and independent TAC-versus-assembly execution. For n instructions and v variables, index construction takes expected O(n) time and O(n+v) space; binary-search queries make complete generation O(n log(n+1)) time and O(n+v) space. A limitation is that analysis follows textual order rather than full control-flow dataflow. The emitted instructions are educational pseudo-assembly, not code for a real processor.")
    assert 150 <= len(abstract.split()) <= 200, len(abstract.split())
    add_par(doc, abstract)
    add_par(doc, "Keywords: three-address code, register allocation, next use, spilling, code generation", size=11, spacing=1.0)

    doc.add_page_break()
    heading(doc, "TABLE OF CONTENTS", 1)
    for entry in [
        "1. Problem Statement and Objectives .................................... 1",
        "2. Theoretical Background ................................................ 1",
        "3. Design and Algorithm .................................................. 2",
        "4. Implementation ........................................................ 3",
        "5. Testing and Results ................................................... 4",
        "6. Complexity and Limitations ........................................... 5",
        "7. AI-Usage Declaration .................................................. 5",
        "8. Conclusion and Future Work ............................................ 5",
        "References ................................................................ 5",
        "Appendix A: Complete Source Code ......................................... 6",
        "Appendix B: AI Usage and Prompt Summary ................................ 18",
        "Appendix C: Additional Test Outputs ..................................... 19",
    ]:
        add_par(doc, entry, size=11, after=2, spacing=1.0)
    heading(doc, "LIST OF FIGURES", 2)
    add_par(doc, "Figure 3.1  TAC translation and register-allocation flow ............. 2", size=10, after=1, spacing=1.0)
    add_par(doc, "Figure 5.1  Basic TAC-to-assembly code generation .................. 4", size=10, after=1, spacing=1.0)
    add_par(doc, "Figure 5.2  Register allocation with spilling and reloading ........ 5", size=10, after=1, spacing=1.0)
    add_par(doc, "Figure C.1  Automated test execution using pytest .................. 20", size=10, after=1, spacing=1.0)
    heading(doc, "LIST OF TABLES", 2)
    add_par(doc, "Table 1.1  Course outcome mapping ..................................... 1", size=10, after=1, spacing=1.0)
    add_par(doc, "Table 4.1  Development environment ................................... 3", size=10, after=1, spacing=1.0)
    add_par(doc, "Table 5.1  Test cases and results .................................... 4", size=10, after=1, spacing=1.0)

    main = doc.add_section(WD_SECTION.NEW_PAGE)
    set_page_geometry(main); main.different_first_page_header_footer = False
    set_header(main, roll="23", visible=True); add_page_num(main, roman=False)

    # Main report follows the template hierarchy; Chapter 5.2 includes the two representative captures.
    heading(doc, "1. PROBLEM STATEMENT AND OBJECTIVES", 1)
    heading(doc, "1.1 Problem statement", 2)
    add_par(doc, "Question Q23 (Compiler Design, medium): “Write a code generator that translates three-address code into assembly for a machine with 3 registers, using a simple getReg routine.” The task is to parse a small TAC language and select among R0, R1, and R2 while preserving each value's meaning through register reuse and memory traffic.")
    heading(doc, "1.2 Objectives", 2)
    add_par(doc, "The objectives are to parse and validate TAC, allocate only three registers, use next-use information to guide eviction, generate assembly-like operations with spill/reload instructions, and check results against a separate TAC evaluator.")
    heading(doc, "1.3 Mapping to CO, BTL and PO", 2)
    add_par(doc, "Table 1.1: Course outcome, Bloom's level and programme outcome mapping", size=10, bold=True, after=3, spacing=1.0)
    add_table(doc, ["Question", "Subject / Level", "CO", "BTL", "PO"], [["Q23", "Compiler Design / Medium", "CO5", "L4", "PO1, PO2, PO4"]], [0.75, 2.1, 0.55, 0.45, 1.6], 10)

    heading(doc, "2. THEORETICAL BACKGROUND", 1)
    heading(doc, "2.1 Concepts and definitions", 2)
    add_par(doc, "A register descriptor records which value is in a register; an address descriptor records where a current value can be found. A value is live when a later instruction reads it before a redefinition. Its next use is the nearest such read. When no register is free, evicting a value with a distant next use often reduces immediate reloads [1], [2].")
    heading(doc, "2.2 Algorithm and worked example", 2)
    add_par(doc, "For `t1 = a + b; x = t1 * 2`, the generator loads `a` and `b`, adds them into a register for `t1`, then multiplies that register by immediate 2 to obtain `x`. If R0=a and R1=b, then R2 receives t1=7 when a=3 and b=4; the next operation writes x=14. At exit x is stored to memory.")

    doc.add_page_break()
    heading(doc, "3. DESIGN AND ALGORITHM", 1)
    heading(doc, "3.1 Overall design", 2)
    add_par(doc, "The flowchart shows the complete translation path, including register pressure and the optional memory path.", size=11)
    create_flowchart()
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.add_run().add_picture(str(FLOWCHART), width=Inches(5.0))
    add_par(doc, "Figure 3.1: TAC translation and register-allocation flow", align=WD_ALIGN_PARAGRAPH.CENTER, size=10, bold=True, after=5, spacing=1.0)
    heading(doc, "3.2 Data structures", 2)
    add_par(doc, "Each instruction stores its kind, destination, operands, operator/comparator, label, and source line. `reg_to_var` and `var_to_reg` are descriptors; `memory_valid` tracks current memory copies; sparse per-variable use/definition events support nearest-next-use queries. A fixed tuple names the only three registers.")
    heading(doc, "3.3 Algorithm", 2)
    add_par(doc, "1) Parse TAC and validate labels. 2) Build sparse use/definition event lists. 3) Reuse or load operands while pinning active sources. 4) Let getReg() choose a free register or the non-pinned value with farthest next use; spill only when its current value is absent from memory. 5) Emit the operation and update descriptors. 6) Flush at branch boundaries and exit.")

    heading(doc, "4. IMPLEMENTATION", 1)
    heading(doc, "4.1 Environment and tools", 2)
    add_par(doc, "Table 4.1: Development environment", size=10, bold=True, after=3, spacing=1.0)
    add_table(doc, ["Item", "Details"], [["Language", "Python 3.13; generator uses only the standard library"], ["Tests", "22 pytest cases after parameter expansion"], ["Operating system", "Windows 11 environment"], ["Output", "Readable educational pseudo-assembly"]], [1.3, 4.2], 10)
    heading(doc, "4.2 getReg routine", 2)
    add_par(doc, "The routine protects active operands, prefers dead values, then evicts the value with the farthest indexed next use. A store is emitted only if memory does not already hold that value.")
    add_code_box(doc, getreg_source_snippet())
    add_par(doc, "Listing 4.1: Core getReg() routine (25 lines maximum)", align=WD_ALIGN_PARAGRAPH.CENTER, size=10, bold=True, after=4, spacing=1.0)
    heading(doc, "4.3 Program structure and input format", 2)
    add_par(doc, "`parse_tac()` builds validated instructions; `analyze_liveness()` creates the sparse event index; `getReg()`, `load()`, `bind()`, and `flush()` manage allocation; `generate()` emits code; and `main()` handles file, standard-input, and output-file use. TAC has one statement per line and supports arithmetic assignments, read, print, return, labels, jumps, and six comparisons. `#` starts a comment; invalid lines and labels are rejected with line numbers.")

    heading(doc, "5. TESTING AND RESULTS", 1)
    heading(doc, "5.1 Test plan", 2)
    add_par(doc, "The test table below is calculated at report-build time from an independent TAC evaluator and an interpreter of the emitted instructions. The full test suite is run separately; any mismatch stops report generation.")
    add_par(doc, "Table 5.1: Executed test cases and results", size=10, bold=True, after=3, spacing=1.0)
    add_table(doc, ["TC No.", "Input", "Expected Output", "Actual Output", "Pass/Fail"],
              build_test_table_rows(), [0.62, 1.35, 1.25, 1.58, 0.75], 10)
    heading(doc, "5.2 Output screenshots", 2)
    add_par(doc, "Figure 5.1 shows TAC translated into assembly-like instructions using only R0, R1, and R2.", size=10, after=2, spacing=1.0)
    add_screenshot_figure(doc, BASIC_SCREENSHOT, "Figure 5.1: Basic TAC-to-Assembly Code Generation", width=5.4)
    add_par(doc, "Figure 5.2 shows temporary values stored in memory when all registers are occupied and reloaded when a later instruction needs them.", size=10, after=2, spacing=1.0)
    add_screenshot_figure(doc, SPILL_SCREENSHOT, "Figure 5.2: Register Allocation with Spilling and Reloading", width=5.4)
    heading(doc, "5.3 Discussion of results", 2)
    add_par(doc, "Independent TAC and assembly execution agreed on arithmetic, I/O, branches, and register-pressure cases; all 22 automated tests passed.", size=10, after=3, spacing=1.0)

    heading(doc, "6. COMPLEXITY AND LIMITATIONS", 1)
    heading(doc, "6.1 Time and space complexity", 2)
    add_par(doc, "For n instructions, v variables, and e <= 3n use/definition events, sparse indexing takes expected O(n) time and O(n+v) space. Binary-search next-use queries give O(n log(n+1)) total generation time; three-register victim checks are constant time. Dense per-instruction snapshots would instead cost O(nv) time and space.", size=10, after=3, spacing=1.0)
    heading(doc, "6.2 Limitations", 2)
    add_par(doc, "Analysis follows textual order rather than CFG-wide dataflow; branches flush memory. The educational pseudo-ISA lacks machine encoding, types, calling conventions, and scheduling; division uses Python floor semantics.", size=10, after=3, spacing=1.0)

    heading(doc, "7. AI-USAGE DECLARATION", 1)
    add_par(doc, "ChatGPT supported assignment explanations, development planning, troubleshooting, and report review. OpenAI Codex (model identifier GPT-6 as displayed in this session) modified the local source, tests, documentation, report, and package. Some submitted content was AI-generated; the student reviewed report versions and should verify and understand the generated code before signing.", size=10, after=3, spacing=1.0)
    heading(doc, "7.1 Critical review of AI output", 2)
    add_par(doc, "Review addressed dense liveness snapshots, spill/reload tracking, operand pinning, parsing, test expectations, and report accuracy. Appendix B summarizes the interaction stages; the retained prompt record is in AI_PROMPT_HISTORY.md.", size=10, after=3, spacing=1.0)

    heading(doc, "8. CONCLUSION AND FUTURE WORK", 1)
    add_par(doc, "The tested generator translates TAC with three registers and verified spill/reload behavior. Future work includes CFG-wide analysis and a real target ISA.", size=10, after=3, spacing=1.0)
    heading(doc, "REFERENCES", 1)
    add_par(doc, "[1] A. V. Aho, M. S. Lam, R. Sethi, and J. D. Ullman, Compilers: Principles, Techniques, and Tools, 2nd ed. Boston, MA, USA: Pearson, 2006.", size=10, spacing=1.0, after=2)
    add_par(doc, "[2] A. V. Aho, R. Sethi, and J. D. Ullman, Compilers: Principles, Techniques, and Tools. Reading, MA, USA: Addison-Wesley, 1986.", size=10, spacing=1.0, after=2)

    # Appendices start after the main report and are excluded from the page budget.
    doc.add_page_break()
    heading(doc, "APPENDIX A: COMPLETE SOURCE CODE", 1)
    add_par(doc, "The complete implementation and automated tests follow. Line numbers are included for reference.", size=10)
    add_code(doc, "src/code_generator.py", (ROOT / "src" / "code_generator.py").read_text(encoding="utf-8"))
    add_code(doc, "tests/test_codegen.py", (ROOT / "tests" / "test_codegen.py").read_text(encoding="utf-8"))

    heading(doc, "APPENDIX B: AI USAGE AND PROMPT SUMMARY", 1)
    doc.paragraphs[-1].paragraph_format.page_break_before = True
    add_par(doc, "The table gives chronological prompt summaries, not verbatim quotations. The original recorded Codex prompts are retained separately in AI_PROMPT_HISTORY.md. ChatGPT is credited for explanations, planning, review, and troubleshooting; Codex is credited for project-file implementation and edits.", size=10, after=5, spacing=1.0)
    add_table(doc,
              ["Date or development stage", "AI tool used", "Prompt or prompt summary", "Assistance received", "Review, correction or action performed"],
              build_ai_history_rows(), [0.9, 0.8, 1.35, 1.3, 1.35], 8.5)

    doc.add_page_break()
    heading(doc, "APPENDIX C: ADDITIONAL TEST OUTPUTS", 1)
    add_par(doc, "The following excerpts are the generator's actual stdout captured from the verified runs; comments and prompts are not added.", size=10)
    for name in ("sample1.tac", "sample3.tac"):
        import subprocess, sys
        output = subprocess.run([sys.executable, str(ROOT / "src" / "code_generator.py"), str(ROOT / "samples" / name)], capture_output=True, text=True, check=True).stdout
        add_par(doc, f"Run for {name}", size=10, bold=True, after=2, spacing=1.0)
        for line in output.strip().splitlines():
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(0); p.paragraph_format.line_spacing = 1.0
            set_font(p.add_run(line), "Courier New", 8)
    add_par(doc, "The remaining city and date fields are placeholders. No handwritten signature is supplied.", size=10, italic=True)

    doc.add_page_break()
    heading(doc, "APPENDIX C: ADDITIONAL TEST OUTPUTS (CONTINUED)", 1)
    add_par(doc, "Figure C.1 shows the actual pytest terminal result: 22 tests passed, with one non-failing pytest deprecation warning.", size=10)
    add_screenshot_figure(doc, PYTEST_SCREENSHOT, "Figure C.1: Automated Test Execution Using Pytest", width=5.4)

    # Set updateFields for page fields and retain template's underlying geometry/styles.
    settings = doc.settings._element
    update = settings.find(qn("w:updateFields"))
    if update is None:
        update = OxmlElement("w:updateFields"); settings.append(update)
    update.set(qn("w:val"), "true")
    doc.core_properties.title = "Q23 Three Register TAC Code Generator Report"
    doc.core_properties.subject = "Automata Theory and Compiler Design 25CS3506"
    doc.core_properties.author = "Shreyas S Harapanahalli"
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    report()
