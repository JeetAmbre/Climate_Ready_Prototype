"""PDF report (ReportLab). Reads the finished assessment; performs no scientific calculation."""
import io
import math
from xml.sax.saxutils import escape as esc
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (BaseDocTemplate, Flowable, Frame, Image, KeepTogether, PageBreak,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

import config

GREEN, TEXT, MUTED, BORDER = colors.HexColor("#166534"), colors.HexColor("#17201A"), colors.HexColor("#64748B"), colors.HexColor("#E2E8F0")
HAZARDS = ["uhi", "waterlogging", "air_pollution"]
TITLES = {"uhi": "Urban Heat Island", "waterlogging": "Waterlogging", "air_pollution": "Air Pollution"}
PAGE_W = A4[0] - 2 * 0.8 * inch

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], textColor=GREEN, fontSize=20, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=TEXT, fontSize=14, spaceBefore=10, spaceAfter=6)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], textColor=TEXT, fontSize=11, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("B", parent=ss["BodyText"], textColor=TEXT, fontSize=9.5, leading=13)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=8, textColor=MUTED, leading=10)


def _hex(c):
    return colors.HexColor(c if c.startswith("#") else "#" + c)


class MapFigure(Flowable):
    """Title + map image + legend + north arrow + scale bar on a white background."""

    def __init__(self, png, bounds, title, legend, width, max_h, rings=None):
        super().__init__()
        self.png, self.bounds, self.title, self.legend, self.rings = png, bounds, title, legend, rings or []
        reader = ImageReader(io.BytesIO(png))
        iw, ih = reader.getSize()
        self.reader = reader
        self.title_h, self.legend_h = 16, 34
        avail_h = max_h - self.title_h - self.legend_h
        s = min(width / iw, avail_h / ih)
        self.iw, self.ih = iw * s, ih * s
        self.width, self.height = width, self.title_h + self.ih + self.legend_h

    def wrap(self, *_):
        return self.width, self.height

    def draw(self):
        c = self.canv
        top = self.height
        c.setFont("Helvetica-Bold", 9.5); c.setFillColor(TEXT)
        c.drawString(0, top - 11, self.title)
        x0, y0 = (self.width - self.iw) / 2, self.legend_h
        c.drawImage(self.reader, x0, y0, self.iw, self.ih, mask="auto")
        c.setStrokeColor(BORDER); c.rect(x0, y0, self.iw, self.ih, stroke=1, fill=0)
        # study-area boundary (images are Web Mercator, like the web map)
        bx0, by0, bx1, by1 = self.bounds
        merc = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
        m0, m1 = merc(by0), merc(by1)
        if self.rings and bx1 > bx0 and m1 > m0:
            c.saveState(); c.setStrokeColor(TEXT); c.setLineWidth(0.8)
            p = c.beginPath()
            for ring in self.rings:
                for n, (lon, lat) in enumerate(ring):
                    px, py = x0 + (lon - bx0) / (bx1 - bx0) * self.iw, y0 + (merc(lat) - m0) / (m1 - m0) * self.ih
                    p.moveTo(px, py) if n == 0 else p.lineTo(px, py)
                p.close()
            c.drawPath(p, stroke=1, fill=0); c.restoreState()
        # north arrow
        ax, ay = x0 + self.iw - 14, y0 + self.ih - 30
        c.setFillColor(TEXT); p = c.beginPath(); p.moveTo(ax, ay + 18); p.lineTo(ax - 5, ay); p.lineTo(ax + 5, ay); p.close()
        c.drawPath(p, fill=1, stroke=0); c.setFont("Helvetica-Bold", 7); c.drawCentredString(ax, ay - 8, "N")
        # scale bar (equirectangular: km per degree longitude shrinks with cos(lat))
        minx, miny, maxx, maxy = self.bounds
        km_w = (maxx - minx) * 111.32 * math.cos(math.radians((miny + maxy) / 2))
        km_pt = km_w / self.iw
        nice = next((v for v in (1, 2, 5, 10, 20, 25, 50, 100) if v / km_pt >= 40), 100)
        bar = nice / km_pt
        c.setStrokeColor(TEXT); c.setLineWidth(1.4)
        c.line(x0 + 6, y0 + 8, x0 + 6 + bar, y0 + 8)
        c.setFont("Helvetica", 7); c.setFillColor(TEXT); c.drawString(x0 + 6, y0 + 12, f"{nice} km")
        # legend
        lg = self.legend
        c.setFont("Helvetica", 7)
        if lg["type"] == "classes":
            step = self.width / 5
            for i, it in enumerate(lg["items"]):
                c.setFillColor(_hex(it["color"])); c.rect(i * step, 18, 10, 8, stroke=0, fill=1)
                c.setFillColor(TEXT); c.drawString(i * step + 13, 19, it["label"])
        else:
            pal, n = lg["palette"], len(lg["palette"])
            w = min(self.width * 0.6, 200)
            for i, col in enumerate(pal):
                c.setFillColor(_hex(col)); c.rect(i * w / n, 18, w / n, 8, stroke=0, fill=1)
            c.setFillColor(TEXT)
            unit = f" {lg['unit']}" if lg.get("unit") and "score" not in lg["unit"] else ""
            c.drawString(0, 8, f"{lg['min']:g}{unit}"); c.drawRightString(w, 8, f"{lg['max']:g}{unit}")
            c.setFillColor(MUTED); c.drawString(w + 8, 19, "Low value  →  High value")


def _bar(pct, color, w=110, h=7):
    from reportlab.graphics.shapes import Drawing, Rect
    d = Drawing(w, h)
    d.add(Rect(0, 0, w, h, fillColor=colors.HexColor("#F1F5F9"), strokeColor=None))
    d.add(Rect(0, 0, w * min(pct, 100) / 100, h, fillColor=_hex(color), strokeColor=None))
    return d


def _fmt_pop(v):
    return f"{v/1e6:.2f} million" if v >= 1e6 else f"{v:,.0f}"


def _table(data, widths, header=True):
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), TEXT),
                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _find_logo():
    d = config.BASE_DIR / "static" / "images"
    for n in config.LOGO_CANDIDATES:
        if (d / n).exists():
            return d / n
    for p in sorted(d.glob("*")):
        if "logo" in p.name.lower() and "favicon" not in p.name.lower() and p.suffix.lower() in (".png", ".jpg", ".jpeg"):
            return p
    return None


def _footer(canvas, doc):
    canvas.saveState(); canvas.setFont("Helvetica", 8); canvas.setFillColor(MUTED)
    canvas.drawString(0.8 * inch, 0.5 * inch, "ClimateReady · Climate Resilience Report")
    canvas.drawRightString(A4[0] - 0.8 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _rings(geom):
    """Outline coordinates of the study area (for drawing the boundary on every map)."""
    geom = geom.simplify(0.001, preserve_topology=True)
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    out = []
    for p in polys:
        if p.geom_type != "Polygon":
            continue
        out.append(list(p.exterior.coords))
        out += [list(r.coords) for r in p.interiors]
    return out


def _figure(png, bounds, title, legend, width, max_h, rings):
    """A map, or a short note if that map could not be produced."""
    if not png:
        return Paragraph(f"<b>{esc(title)}</b><br/><br/>This map could not be rendered.", SMALL)
    try:
        return MapFigure(png, bounds, title, legend, width, max_h, rings)
    except Exception:
        return Paragraph(f"<b>{esc(title)}</b><br/><br/>This map could not be rendered.", SMALL)


def generate_report(job, pngs, palettes):
    """job: finished assessment. pngs: {layer_id: png bytes}. palettes: {hazard: [hex,...]}."""
    buf = io.BytesIO()
    S, ov = [], job.stats["overview"]
    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                          topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                          title=f"ClimateReady Resilience Report - {ov['location']}")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")], onPage=_footer)])

    # ---------- cover ----------
    S.append(Spacer(1, 1.6 * inch))
    logo = _find_logo()
    if logo:
        r = ImageReader(str(logo)); w, h = r.getSize(); sh = 1.1 * inch
        S.append(Image(str(logo), width=sh * w / h, height=sh, hAlign="LEFT"))
    S += [Spacer(1, 10), Paragraph("ClimateReady", ParagraphStyle("c1", parent=H1, fontSize=34, leading=42, textColor=GREEN)),
          Paragraph("Climate Resilience Report", ParagraphStyle("c2", parent=H2, fontSize=20, leading=26)), Spacer(1, 40),
          Paragraph("Study Location", SMALL), Paragraph(esc(ov["location"]), ParagraphStyle("c3", parent=BODY, fontSize=14, leading=18)),
          Spacer(1, 14), Paragraph("Assessment date", SMALL), Paragraph(date.today().strftime("%d %B %Y"), BODY),
          Spacer(1, 150), Paragraph("From Climate Risk to Local Action.", ParagraphStyle("c4", parent=BODY, textColor=MUTED)),
          PageBreak()]

    # ---------- overview / statistics ----------
    S.append(Paragraph("Assessment Overview", H1))
    S.append(_table([["Study area", ov["location"]], ["Total area", f"{ov['area_km2']:,.1f} km²"],
                     ["Population (WorldPop 2020)", _fmt_pop(ov["population"])],
                     ["Approx. centre", f"{ov['lat']:.4f}° N, {ov['lng']:.4f}° E"]], [2.0 * inch, PAGE_W - 2.0 * inch], header=False))
    if job.warnings:
        S.append(Spacer(1, 6))
        S.append(Paragraph("<b>Data not available for this area:</b> " + esc("; ".join(job.warnings)) +
                           ". A neutral score (3, the midpoint of the 1-5 scale) was used for missing indicators in the hazard calculation.", SMALL))
    S.append(Paragraph("Final risk = hazard index × socio-economic vulnerability index ÷ 5. Statistics below are calculated from the final risk maps.", SMALL))
    for hz in HAZARDS:
        h = job.stats["hazards"][hz]; pal = palettes[hz]
        S.append(Paragraph(f"{TITLES[hz]} Risk", H2))
        rows = [["", "Risk level", "Area (km²)", "% of area", "", "Population", "% of population"]]
        for r in reversed(h["rows"]):
            rows.append(["", r["level"], f"{r['area_km2']:,.2f}", f"{r['area_pct']:.1f}%", _bar(r["area_pct"], pal[r["class"] - 1]),
                         f"{r['population']:,.0f}", f"{r['population_pct']:.1f}%"])
        t = _table(rows, [14, 0.9 * inch, 0.9 * inch, 0.8 * inch, 1.5 * inch, 0.95 * inch, PAGE_W - 14 - 5.05 * inch])
        for i, r in enumerate(reversed(h["rows"]), start=1):
            t.setStyle(TableStyle([("BACKGROUND", (0, i), (0, i), _hex(pal[r["class"] - 1]))]))
        S.append(KeepTogether([t]))
    S.append(Paragraph("Percentage of area and percentage of population are different measures; each sums to 100% within its own column.", SMALL))
    S.append(PageBreak())

    # ---------- hazard sections ----------
    bounds = job.aoi["bounds"]
    rings = _rings(job.aoi["geom"])
    for hz in HAZARDS:
        fw = job.frameworks[hz]
        S.append(Paragraph(TITLES[hz], H1))
        S.append(Paragraph(f"{TITLES[hz]} Risk Map", H2))
        lyr = job.layers[f"risk_{hz}"]
        S.append(_figure(pngs.get(f"risk_{hz}"), bounds, f"{TITLES[hz]} Risk", lyr["legend"], PAGE_W, 6.2 * inch, rings))
        S.append(PageBreak())
        S.append(Paragraph(f"{TITLES[hz]} Indicators", H2))
        S.append(Paragraph("Indicator maps show the underlying data; weights are the AHP weights from the research framework.", SMALL))
        cells, w = [], PAGE_W / 2 - 6
        for ind in fw.indicators:
            lid = f"ind_{hz}_{ind.key}"
            cap = f"{ind.label} (weight {ind.weight:.3f})"
            if not ind.available:
                cells.append(Paragraph(f"<b>{esc(cap)}</b><br/><br/>Data not available for this area.", SMALL))
                continue
            cells.append(_figure(pngs.get(lid), bounds, cap, job.layers[lid]["legend"], w, 3.5 * inch, rings))
        if len(cells) % 2:
            cells.append(Spacer(1, 1))
        grid = Table([cells[i:i + 2] for i in range(0, len(cells), 2)], colWidths=[PAGE_W / 2] * 2)
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        S += [grid, PageBreak()]

    # ---------- socio-economic indicators section ----------
    if "socio" in job.frameworks:
        fw = job.frameworks["socio"]
        S.append(Paragraph("Socio-Economic Indicators", H1))
        S.append(Paragraph("Socio-Economic Indicators", H2))
        S.append(Paragraph("Indicator maps show the underlying socio-economic vulnerability data; weights are the AHP weights from the research framework.", SMALL))
        cells, w = [], PAGE_W / 2 - 6
        for ind in fw.indicators:
            lid = f"ind_socio_{ind.key}"
            cap = f"{ind.label} (weight {ind.weight:.3f})"
            if not ind.available:
                cells.append(Paragraph(f"<b>{esc(cap)}</b><br/><br/>Data not available for this area.", SMALL))
                continue
            cells.append(_figure(pngs.get(lid), bounds, cap, job.layers[lid]["legend"], w, 3.5 * inch, rings))
        if len(cells) % 2:
            cells.append(Spacer(1, 1))
        grid = Table([cells[i:i + 2] for i in range(0, len(cells), 2)], colWidths=[PAGE_W / 2] * 2)
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        S += [grid, PageBreak()]

    # ---------- recommendations ----------
    S.append(Paragraph("Recommended Local Actions", H1))
    recs = job.recs or []
    if not recs:
        S.append(Paragraph("No priority areas (Moderate or above) were identified in the study area.", BODY))
    for r in recs:
        rows = [[Paragraph(f"<b>{esc(r['hazard_label'])}</b> · {esc(r['priority'])}", BODY), ""],
                ["Location", Paragraph(f"{esc(r['place'])} (approx. {r['lat']:.4f}° N, {r['lng']:.4f}° E)", BODY)],
                ["Risk", Paragraph(esc(r["addresses"]), BODY)],
                ["Primary indicator", Paragraph(esc(r["indicator"]) + (f" (also: {esc(r['also'])})" if r["also"] else ""), BODY)],
                ["Recommended action", Paragraph(esc(r["action"]), BODY)], ["Why", Paragraph(esc(r["why"]), BODY)]]
        t = Table(rows, colWidths=[1.4 * inch, PAGE_W - 1.4 * inch])
        t.setStyle(TableStyle([("SPAN", (0, 0), (1, 0)), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCFCE7")),
                               ("FONTSIZE", (0, 1), (0, -1), 8.5), ("TEXTCOLOR", (0, 1), (0, -1), MUTED), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("BOX", (0, 0), (-1, -1), 0.5, BORDER)]))
        S += [KeepTogether([t]), Spacer(1, 8)]
    S.append(Paragraph("Results are a decision-support assessment and should be read alongside local knowledge and detailed planning studies.", SMALL))
    doc.build(S)
    return buf.getvalue()
