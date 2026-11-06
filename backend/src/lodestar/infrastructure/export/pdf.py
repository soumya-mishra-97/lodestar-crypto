"""PDF export (fpdf2: pure Python, no system libraries) from the same outline as Markdown."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from lodestar.application.exports import claim_line, outline

_REPLACEMENTS = {
    "—": "-",
    "–": "-",
    "−": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    "·": "-",
    "±": "+/-",
    "→": "->",
    "≈": "~",
}


def latin1(text: str) -> str:
    """Core PDF fonts are Latin-1 only: map common typography, replace anything else."""
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


class FpdfReportRenderer:
    def render(self, report: Mapping[str, Any]) -> bytes:
        pdf = FPDF(format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_title(latin1(f"Lodestar report {report['content']['asset']['symbol']}"))
        pdf.set_creator("Lodestar")
        pdf.add_page()
        width = pdf.w - pdf.l_margin - pdf.r_margin

        def line(text: str, size: float = 10, style: str = "", gap: float = 1.5, color: int = 20) -> None:
            pdf.set_font("Helvetica", style, size)
            pdf.set_text_color(color)
            pdf.multi_cell(width, size * 0.5, latin1(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.ln(gap)

        for block in outline(report):
            match block.kind:
                case "h1":
                    line(block.text, 16, "B", 2)
                case "h2":
                    pdf.ln(2)
                    line(block.text, 13, "B", 1)
                case "h3":
                    line(block.text, 11, "B", 0.5)
                case "p":
                    line(block.text, 10)
                case "small":
                    line(block.text, 8, "I", 2, 90)
                case "claims":
                    for claim in block.claims:
                        line(f"- {claim_line(claim)}", 9.5, gap=0.8)
                    pdf.ln(1)
                case "table":
                    self._table(pdf, block.rows, width)
        out = pdf.output()
        return bytes(out)

    @staticmethod
    def _table(pdf: FPDF, rows: tuple[tuple[str, ...], ...], width: float) -> None:
        if not rows:
            return
        pdf.set_text_color(20)
        with pdf.table(width=width, text_align="LEFT", line_height=4.5, first_row_as_headings=True) as table:
            for i, row in enumerate(rows):
                pdf.set_font("Helvetica", "B" if i == 0 else "", 8)
                r = table.row()
                for cell in row:
                    r.cell(latin1(str(cell))[:160])
        pdf.ln(2)
