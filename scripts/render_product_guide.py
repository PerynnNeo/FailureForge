"""Build the product guide PDF from its editable Markdown source.

Run with the Codex bundled Python runtime (reportlab and pypdf installed).
This renderer supports the deliberately simple Markdown used in the guide.
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table,
    TableStyle, PageBreak, Preformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents


def inline(text: str) -> str:
    text = text.replace('\u2011', '-').replace('\u2013', '-').replace('\u2014', ' - ')
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)', r'<a href="\2" color="#22576C"><u>\1</u></a>', text)
    text = re.sub(r'`([^`]+)`', r'<font name="Mono" size="9.6">\1</font>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<i>\1</i>', text)
    return text


class Guide(BaseDocTemplate):
    def __init__(self, path: str, **kwargs):
        super().__init__(path, pagesize=(612, 792), leftMargin=54, rightMargin=54,
                         topMargin=55, bottomMargin=52, title='FailureForge Product Journeys and Technical Architecture',
                         author='FailureForge', **kwargs)
        self.addPageTemplates(PageTemplate(id='Guide', frames=[Frame(54, 52, 504, 685,
                              leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)],
                              onPage=self.page_frame))
        self._heading_counter = 0

    def beforeDocument(self):
        self._heading_counter = 0

    def page_frame(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor('#000000'))
        canvas.setFont('Body', 8.5)
        canvas.drawString(54, 761, 'FAILUREFORGE')
        canvas.setFillColor(colors.HexColor('#59636A'))
        canvas.drawRightString(558, 761, 'Product journeys and implementation architecture')
        canvas.setFont('Body', 8)
        canvas.drawString(54, 29, '19 November 2026  |  Implementation and staged roadmap')
        canvas.drawRightString(558, 29, str(doc.page))
        canvas.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ('GuideH1', 'GuideH2'):
            level = 0 if flowable.style.name == 'GuideH1' else 1
            self._heading_counter += 1
            key = f'section-{self._heading_counter}'
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, level=level, closed=level == 0)
            if level == 0:
                self.notify('TOCEntry', (0, flowable.getPlainText(), self.page, key))


def make_styles():
    styles = {
        'body': ParagraphStyle('GuideBody', fontName='Body', fontSize=11, leading=15.2,
                               textColor=colors.HexColor('#20272B'), spaceAfter=8, allowWidows=0, allowOrphans=0),
        'title': ParagraphStyle('GuideTitle', fontName='BodyBold', fontSize=26, leading=30,
                                textColor=colors.black, spaceBefore=14, spaceAfter=18, keepWithNext=True),
        'h1': ParagraphStyle('GuideH1', fontName='BodyBold', fontSize=16, leading=20,
                             textColor=colors.black, spaceBefore=19, spaceAfter=10, keepWithNext=True),
        'h2': ParagraphStyle('GuideH2', fontName='BodyBold', fontSize=12.5, leading=16,
                             textColor=colors.black, spaceBefore=13, spaceAfter=7, keepWithNext=True),
        'contents': ParagraphStyle('GuideContents', fontName='BodyBold', fontSize=12.5, leading=16,
                                   textColor=colors.black, spaceBefore=13, spaceAfter=7, keepWithNext=True),
        'table': ParagraphStyle('GuideTable', fontName='Body', fontSize=10, leading=13,
                                textColor=colors.HexColor('#20272B'), spaceAfter=0),
        'thead': ParagraphStyle('GuideTableHead', fontName='BodyBold', fontSize=10, leading=13,
                                textColor=colors.black, spaceAfter=0),
        'bullet': ParagraphStyle('GuideBullet', fontName='Body', fontSize=11, leading=15.2,
                                 leftIndent=15, firstLineIndent=0, bulletIndent=1,
                                 textColor=colors.HexColor('#20272B'), spaceAfter=6, allowWidows=0, allowOrphans=0),
        'code': ParagraphStyle('GuideCode', fontName='Mono', fontSize=9, leading=12,
                               textColor=colors.HexColor('#27343D'), spaceBefore=4, spaceAfter=10),
    }
    return styles


def cells(line):
    return [s.strip() for s in line.strip().strip('|').split('|')]


def render(source: Path, destination: Path):
    fontroot = Path('C:/Windows/Fonts')
    for name, filename in [('Body', 'arial.ttf'), ('BodyBold', 'arialbd.ttf'),
                           ('BodyItalic', 'ariali.ttf'), ('BodyBoldItalic', 'arialbi.ttf'), ('Mono', 'consola.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(fontroot / filename)))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='BodyBold', italic='BodyItalic', boldItalic='BodyBoldItalic')
    styles = make_styles()
    lines = source.read_text(encoding='utf-8-sig').splitlines()
    story = []
    i = 0
    inserted_contents = False
    while i < len(lines):
        line = lines[i].strip()
        if not line or re.fullmatch(r'[-*_]{3,}', line):
            i += 1
            continue
        if line.startswith('```'):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                block.append(lines[i].replace('\t', '    '))
                i += 1
            story.append(Preformatted('\n'.join(block), styles['code'], maxLineLength=91))
            i += 1
            continue
        match = re.match(r'^(#{1,6})\s+(.+)', line)
        if match:
            depth, title = len(match[1]), match[2]
            if depth == 2 and not inserted_contents:
                story.append(Spacer(1, 10))
                story.append(Paragraph('Guide contents', styles['contents']))
                toc = TableOfContents()
                toc.levelStyles = [ParagraphStyle('TOC', fontName='Body', fontSize=10.5,
                                                 leading=14, leftIndent=0, rightIndent=16,
                                                 firstLineIndent=0, spaceBefore=3,
                                                 textColor=colors.HexColor('#20272B'))]
                story.extend([toc, PageBreak()])
                inserted_contents = True
            story.append(Paragraph(inline(title), styles['title' if depth == 1 else 'h1' if depth == 2 else 'h2']))
            i += 1
            continue
        if line.startswith('|') and i + 1 < len(lines) and re.match(r'^\s*\|?\s*:?-{3,}', lines[i + 1]):
            rows = [cells(line)]
            i += 2
            while i < len(lines) and lines[i].strip().startswith('|'):
                rows.append(cells(lines[i]))
                i += 1
            count = len(rows[0])
            weights = [max(12, min(65, sum(len(row[n]) for row in rows if len(row) > n) / len(rows))) for n in range(count)]
            widths = [504 * x / sum(weights) for x in weights]
            if widths[0] < 82:
                remaining = sum(widths[1:])
                widths = [82] + [422 * width / remaining for width in widths[1:]]
            data = [[Paragraph(inline(cell), styles['thead' if ri == 0 else 'table']) for cell in row] for ri, row in enumerate(rows)]
            table = Table(data, colWidths=widths, repeatRows=1, hAlign='LEFT')
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DFE8ED')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F7F8')]),
                ('GRID', (0, 0), (-1, -1), .45, colors.HexColor('#D9D9D9')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            story.extend([table, Spacer(1, 11)])
            continue
        bullet = re.match(r'^([-*]|\d+\.)\s+(.+)', line)
        if bullet:
            story.append(Paragraph(inline(bullet[2]), styles['bullet'], bulletText='\u2022' if bullet[1] in ('-', '*') else bullet[1]))
            i += 1
            continue
        if line.startswith('> '):
            story.append(Paragraph(inline(line[2:]), styles['body']))
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(r'^(#|\||```|>|[-*]\s|\d+\.\s)', lines[i].strip()):
            paragraph.append(lines[i].strip())
            i += 1
        story.append(Paragraph(inline(' '.join(paragraph)), styles['body']))
    destination.parent.mkdir(parents=True, exist_ok=True)
    Guide(str(destination)).multiBuild(story)
    from pypdf import PdfReader
    print(f'Created {destination} ({len(PdfReader(destination).pages)} pages)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=Path('docs/product-journeys-and-architecture.md'))
    parser.add_argument('--output', type=Path, default=Path('output/pdf/failureforge-product-journeys.pdf'))
    args = parser.parse_args()
    render(args.source, args.output)
