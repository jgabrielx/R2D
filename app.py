import os, io, json, sqlite3, uuid, base64
from datetime import datetime
from flask import Flask, request, jsonify, send_file, render_template, abort, g
from PIL import Image as PILImage
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import mm, cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Image, PageBreak, HRFlowable, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY



app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

# ── Paths ──────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'instance', 'reports.db')
PDF_DIR  = os.path.join(BASE_DIR, 'instance', 'pdfs')
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(PDF_DIR, exist_ok=True)

# ── Database ───────────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db: db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''CREATE TABLE IF NOT EXISTS reports (
            id       TEXT PRIMARY KEY,
            agency   TEXT,
            prefix   TEXT,
            os       TEXT,
            contract TEXT,
            fiscal   TEXT,
            date     TEXT,
            address  TEXT,
            created  TEXT,
            pdf_path TEXT,
            n_photos INTEGER DEFAULT 0,
            n_sections INTEGER DEFAULT 0
        )''')
        db.commit()

# ── Constants ──────────────────────────────────────────────────────────────
PAGE_W, PAGE_H = A4
MARGIN    = 1.5 * cm
CONTENT_W = PAGE_W - 2 * MARGIN
DARK   = colors.HexColor("#1a1a1a")
GRAY   = colors.HexColor("#555555")
LGRAY  = colors.HexColor("#cccccc")
LLGRAY = colors.HexColor("#f2f2f2")
WHITE  = colors.white
BORDER = colors.HexColor("#333333")

# ── PDF styles ─────────────────────────────────────────────────────────────
def build_styles():
    base = getSampleStyleSheet()
    def s(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)
    return {
        "hdr_title":   s("hdr_title",   fontSize=9,  fontName="Helvetica-Bold", alignment=TA_CENTER, textColor=DARK),
        "sec_bar":     s("sec_bar",     fontSize=8,  fontName="Helvetica-Bold", textColor=WHITE),
        "field_lbl":   s("field_lbl",   fontSize=7,  fontName="Helvetica-Bold", textColor=DARK),
        "field_val":   s("field_val",   fontSize=8,  fontName="Helvetica",      textColor=DARK),
        "toc_main":    s("toc_main",    fontSize=8.5,fontName="Helvetica-Bold", textColor=DARK),
        "toc_sub":     s("toc_sub",     fontSize=8,  fontName="Helvetica",      textColor=GRAY, leftIndent=20),
        "body":        s("body",        fontSize=8.5,fontName="Helvetica",      textColor=DARK, leading=13, alignment=TA_JUSTIFY),
        "body_title":  s("body_title",  fontSize=8.5,fontName="Helvetica-Bold", textColor=DARK),
        "photo_cap":   s("photo_cap",   fontSize=7.5,fontName="Helvetica",      textColor=DARK, alignment=TA_CENTER),
        "photo_grp":   s("photo_grp",   fontSize=8.5,fontName="Helvetica-Bold", textColor=DARK, alignment=TA_CENTER),
        "photo_num":   s("photo_num",   fontSize=8.5,fontName="Helvetica-Bold", textColor=DARK),
        "tech_sec":    s("tech_sec",    fontSize=9.5,fontName="Helvetica-Bold", textColor=DARK, spaceBefore=6),
        "tech_sub":    s("tech_sub",    fontSize=8.5,fontName="Helvetica-Bold", textColor=DARK, spaceBefore=3),
        "tech_item":   s("tech_item",   fontSize=8.5,fontName="Helvetica",      textColor=DARK, leftIndent=10, leading=13),
        "pg_num":      s("pg_num",      fontSize=7,  fontName="Helvetica",      textColor=GRAY, alignment=TA_RIGHT),
        "cover_date":  s("cover_date",  fontSize=12, fontName="Helvetica-Bold", alignment=TA_CENTER),
    }

# ── Helpers ────────────────────────────────────────────────────────────────
def sec_bar(text, st, width=CONTENT_W):
    t = Table([[Paragraph(text, st["sec_bar"])]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0),(-1,-1), colors.HexColor("#444")),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LEFTPADDING",   (0,0),(-1,-1), 8),
    ]))
    return t

def rl_logo(b64_str, max_h):
    if not b64_str: return None
    try:
        data = base64.b64decode(b64_str)
        pil  = PILImage.open(io.BytesIO(data))
        if pil.mode in ("RGBA","P"): pil = pil.convert("RGB")
        buf  = io.BytesIO(); pil.save(buf, "JPEG", quality=90); buf.seek(0)
        ratio = pil.width / pil.height
        return Image(buf, width=max_h*ratio, height=max_h)
    except: return None

def rl_photo(b64_str, max_w, max_h):
    if not b64_str: return None
    try:
        if "," in b64_str: b64_str = b64_str.split(",",1)[1]
        data = base64.b64decode(b64_str)
        pil  = PILImage.open(io.BytesIO(data))
        if pil.mode in ("RGBA","P"): pil = pil.convert("RGB")
        buf  = io.BytesIO(); pil.save(buf, "JPEG", quality=85); buf.seek(0)
        ratio = pil.width / pil.height
        w = max_w; h = w / ratio
        if h > max_h: h = max_h; w = h * ratio
        return Image(buf, width=w, height=h)
    except: return None

# ── Header ─────────────────────────────────────────────────────────────────
def make_header(st, logo_r2d_b64, logo_bb_b64):
    def logo_cell(b64, max_h):
        img = rl_logo(b64, max_h)
        if img: return [img]
        return [Paragraph("", st["hdr_title"])]

    t = Table([[ logo_cell(logo_r2d_b64, 1.2*cm),
                 [Paragraph("RELATÓRIO FOTOGRÁFICO", st["hdr_title"])],
                 logo_cell(logo_bb_b64,  1.1*cm) ]],
              colWidths=[CONTENT_W*0.25, CONTENT_W*0.5, CONTENT_W*0.25])
    t.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("ALIGN",         (0,0),(0,0),   "LEFT"),
        ("ALIGN",         (1,0),(1,0),   "CENTER"),
        ("ALIGN",         (2,0),(2,0),   "RIGHT"),
        ("TOPPADDING",    (0,0),(-1,-1), 4),
        ("BOTTOMPADDING", (0,0),(-1,-1), 4),
        ("LINEBELOW",     (0,0),(-1,-1), 0.5, LGRAY),
    ]))
    return t

# ── Cover ──────────────────────────────────────────────────────────────────
def build_cover(data, st, logo_r2d_b64, logo_bb_b64):
    story = []
    inner = []

    def logo_cell(b64, max_h):
        img = rl_logo(b64, max_h)
        if img: return img
        return Paragraph("R2D", st["cover_date"])

    logo_tbl = Table([[logo_cell(logo_r2d_b64, 2.2*cm),
                       Spacer(0.5*cm, 1),
                       logo_cell(logo_bb_b64, 2.0*cm)]],
                     colWidths=[CONTENT_W*0.38, CONTENT_W*0.24, CONTENT_W*0.38])
    logo_tbl.setStyle(TableStyle([
        ("VALIGN",        (0,0),(-1,-1), "MIDDLE"),
        ("ALIGN",         (0,0),(0,0),   "CENTER"),
        ("ALIGN",         (2,0),(2,0),   "CENTER"),
        ("LINEBELOW",     (0,0),(-1,-1), 0.5, LGRAY),
        ("BOTTOMPADDING", (0,0),(-1,-1), 14),
    ]))
    inner += [Spacer(1, 4*cm), logo_tbl,
              Spacer(1, 4*cm),
              Paragraph(f"Rio de Janeiro {data.get('date','')}", st["cover_date"]),
              Spacer(1, 3*cm)]

    wrap = Table([[e] for e in inner], colWidths=[CONTENT_W - 2*cm])
    wrap.setStyle(TableStyle([("BOX",(0,0),(-1,-1),1.5,BORDER),
                               ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
                               ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
    outer = Table([[wrap]], colWidths=[CONTENT_W])
    outer.setStyle(TableStyle([("BOX",(0,0),(-1,-1),3,BORDER),
                                ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
                                ("LEFTPADDING",(0,0),(-1,-1),8),("RIGHTPADDING",(0,0),(-1,-1),8)]))
    story += [outer, PageBreak()]
    return story

# ── Info + Sumário ─────────────────────────────────────────────────────────
def build_info_summary(data, st, logo_r2d_b64, logo_bb_b64, photos, tech):
    story = []
    story += [make_header(st, logo_r2d_b64, logo_bb_b64), Spacer(1,4*mm)]
    story.append(sec_bar("INFORMAÇÕES GERAIS", st))
    story.append(Spacer(1,2*mm))

    def row(a_lbl, a_val, b_lbl, b_val, full=False):
        if full:
            return [[Paragraph(a_lbl, st["field_lbl"]), ""],
                    [Paragraph(a_val, st["field_val"]), ""]]
        return [[Paragraph(a_lbl, st["field_lbl"]), Paragraph(b_lbl, st["field_lbl"])],
                [Paragraph(a_val, st["field_val"]), Paragraph(b_val, st["field_val"])]]

    def lv(k): return data.get(k,"") or ""

    rows = (row("Agência","","Prefixo","") +
            row(lv("agency"),"",lv("prefix"),"") +
            row("Endereço:","","","",True) +
            row(lv("address"),"","","",True) +
            row("Data:","","Fiscal:","") +
            row(lv("date"),"",lv("fiscal"),"") +
            row("Contrato:","","O.S.:","") +
            row(lv("contract"),"",lv("os"),""))

    # rebuild properly
    info_data = [
        [Paragraph("<b>Agência</b>",  st["field_lbl"]), Paragraph("<b>Prefixo</b>", st["field_lbl"])],
        [Paragraph(lv("agency"),      st["field_val"]), Paragraph(lv("prefix"),     st["field_val"])],
        [Paragraph("<b>Endereço:</b>",st["field_lbl"]), ""],
        [Paragraph(lv("address"),     st["field_val"]), ""],
        [Paragraph("<b>Data:</b>",    st["field_lbl"]), Paragraph("<b>Fiscal:</b>", st["field_lbl"])],
        [Paragraph(lv("date"),        st["field_val"]), Paragraph(lv("fiscal"),     st["field_val"])],
        [Paragraph("<b>Contrato:</b>",st["field_lbl"]), Paragraph("<b>O.S.:</b>",   st["field_lbl"])],
        [Paragraph(lv("contract"),    st["field_val"]), Paragraph(lv("os"),         st["field_val"])],
    ]
    it = Table(info_data, colWidths=[CONTENT_W*.5, CONTENT_W*.5])
    it.setStyle(TableStyle([
        ("BOX",       (0,0),(-1,-1), .5, LGRAY),
        ("INNERGRID", (0,0),(-1,-1), .3, LLGRAY),
        ("SPAN",(0,2),(1,2)),("SPAN",(0,3),(1,3)),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story += [it, Spacer(1,4*mm)]
    story.append(sec_bar("SUMÁRIO", st))
    story.append(Spacer(1,3*mm))

    toc = [
        [Paragraph("<b>1.</b>",st["toc_main"]), Paragraph("<b>DADOS GERAIS</b>",st["toc_main"]),  Paragraph("",st["toc_main"])],
    ]
    for num,title,pg in [("1.1","Apresentação do documento","2"),("1.2","Objeto do Documento","2"),("1.3","Finalidade do Documento","2")]:
        toc.append([Paragraph(num,st["toc_sub"]), Paragraph(title,st["toc_sub"]), Paragraph(pg,st["toc_sub"])])
    toc.append([Paragraph("<b>2.</b>",st["toc_main"]), Paragraph("<b>RELATÓRIO FOTOGRÁFICO</b>",st["toc_main"]), Paragraph("<b>3</b>",st["toc_main"])])
    page = 3
    for i,ph in enumerate(photos):
        if i>0 and i%2==0: page+=1
        toc.append([Paragraph(f"2.{i+1}",st["toc_sub"]), Paragraph(ph.get("group",""),st["toc_sub"]), Paragraph(str(page),st["toc_sub"])])

    tt = Table(toc, colWidths=[CONTENT_W*.12, CONTENT_W*.76, CONTENT_W*.12])
    tt.setStyle(TableStyle([("TOPPADDING",(0,0),(-1,-1),1.5),("BOTTOMPADDING",(0,0),(-1,-1),1.5),
                             ("LEFTPADDING",(0,0),(-1,-1),4),("ALIGN",(2,0),(2,-1),"RIGHT")]))
    story += [tt, Spacer(1,3*mm), HRFlowable(width=CONTENT_W, thickness=0.5, color=LGRAY),
              Paragraph("1", st["pg_num"]), PageBreak()]
    return story

# ── Dados Gerais ───────────────────────────────────────────────────────────
def build_dados(data, st, logo_r2d_b64, logo_bb_b64):
    story = []
    story += [make_header(st,logo_r2d_b64,logo_bb_b64), Spacer(1,4*mm)]
    def lv(k): return data.get(k,"") or ""
    T1 = lv("presentation") or ("O presente relatório apresenta os registros da visita técnica realizada "
         "na unidade do Banco do Brasil, com o objetivo de levantamento das condições existentes "
         "no local para futura execução dos serviços contratados.")
    T2 = lv("objective") or ("Este documento tem por objeto o registro detalhado da visita técnica "
         "realizada na agência supracitada, contemplando aspectos estruturais, arquitetônicos, "
         "elétricos, hidráulicos, de climatização e demais instalações relevantes à execução dos "
         "serviços de obra ou manutenção.")
    T3 = lv("purpose") or ("O relatório fotográfico tem como finalidade registrar as condições "
         "observadas durante a visita técnica, incluindo análise de conformidade, identificação "
         "de possíveis problemas e recomendações técnicas. Tem como objetivo documentar a situação "
         "atual, fornecer diretrizes para ações corretivas e subsidiar tomadas de decisão.")
    bar = Table([[Paragraph("<b>1.</b>",st["sec_bar"]), Paragraph("<b>DADOS GERAIS</b>",st["sec_bar"])]],
                colWidths=[CONTENT_W*.08, CONTENT_W*.92])
    bar.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#444")),
                              ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                              ("LEFTPADDING",(0,0),(-1,-1),6)]))
    story += [bar, Spacer(1,3*mm), Paragraph(f"Rio de Janeiro, {lv('date')}", st["body"]), Spacer(1,3*mm)]
    for num,title,txt in [("1.1","APRESENTAÇÃO",T1),("1.2","OBJETO DO DOCUMENTO",T2),("1.3","FINALIDADE DO DOCUMENTO",T3)]:
        story += [Paragraph(f"<b>{num}  {title}</b>", st["body_title"]), Spacer(1,2*mm),
                  Paragraph(txt, st["body"]), Spacer(1,4*mm)]
    story += [HRFlowable(width=CONTENT_W, thickness=0.5, color=LGRAY), Paragraph("2",st["pg_num"]), PageBreak()]
    return story

# ── Fotos ──────────────────────────────────────────────────────────────────
def build_photos(data, st, logo_r2d_b64, logo_bb_b64, photos):
    story = []
    date_str = data.get("date","")
    page = 3
    for i in range(0, len(photos), 2):
        story.append(make_header(st, logo_r2d_b64, logo_bb_b64))
        hbar = Table([[Paragraph("<b>RELATÓRIO FOTOGRÁFICO</b>", st["sec_bar"]),
                       Paragraph(f"<b>{date_str}</b>",
                                 ParagraphStyle("ph2",fontSize=8,fontName="Helvetica-Bold",
                                                textColor=WHITE,alignment=TA_RIGHT))]],
                     colWidths=[CONTENT_W*.7, CONTENT_W*.3])
        hbar.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1),colors.HexColor("#555")),
                                   ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                                   ("LEFTPADDING",(0,0),(-1,-1),6),("RIGHTPADDING",(0,0),(-1,-1),6)]))
        story += [Spacer(1,1*mm), hbar, Spacer(1,3*mm)]

        for ph in photos[i:i+2]:
            idx = photos.index(ph)
            group   = ph.get("group","")
            caption = ph.get("caption","")
            title_row = Table([[Paragraph(f"2.{idx+1}",st["photo_num"]),
                                Paragraph(f"<b>{group}</b>", st["photo_grp"])]],
                              colWidths=[CONTENT_W*.1, CONTENT_W*.9])
            title_row.setStyle(TableStyle([
                ("BOX",(0,0),(-1,-1),.5,LGRAY),("BACKGROUND",(0,0),(-1,-1),LLGRAY),
                ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
                ("LEFTPADDING",(0,0),(-1,-1),6),
            ]))
            elements = [title_row]
            img = rl_photo(ph.get("image",""), CONTENT_W-1.2*cm, 7.2*cm)
            if img:
                ic = Table([[img]], colWidths=[CONTENT_W])
                ic.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                                         ("TOPPADDING",(0,0),(-1,-1),6),("BOTTOMPADDING",(0,0),(-1,-1),6)]))
                elements.append(ic)
            else:
                elements.append(Spacer(1, 7.2*cm))
            cap_row = Table([[Paragraph(caption, st["photo_cap"])]], colWidths=[CONTENT_W])
            cap_row.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),
                                          ("BOX",(0,0),(-1,-1),.5,LGRAY),
                                          ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5)]))
            elements.append(cap_row)
            box = Table([[e] for e in elements], colWidths=[CONTENT_W])
            box.setStyle(TableStyle([("BOX",(0,0),(-1,-1),.7,BORDER),
                                      ("TOPPADDING",(0,0),(-1,-1),0),("BOTTOMPADDING",(0,0),(-1,-1),0),
                                      ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)]))
            story += [KeepTogether([box]), Spacer(1,4*mm)]

        story += [HRFlowable(width=CONTENT_W, thickness=0.5, color=LGRAY), Paragraph(str(page),st["pg_num"]), PageBreak()]
        page += 1
    return story

# ── Relatório Técnico ──────────────────────────────────────────────────────
def build_tech(data, st, logo_r2d_b64, logo_bb_b64, tech, n_photos):
    story = []
    story += [make_header(st,logo_r2d_b64,logo_bb_b64), Spacer(1,3*mm)]
    def lv(k): return data.get(k,"") or ""
    story += [
        Paragraph(f"<b>TÍTULO:</b> Relatório Técnico de Vistoria – {lv('report_title') or 'Cobertura e Instalações'}", st["body"]),
        Paragraph(f"<b>AGÊNCIA:</b> {lv('client_name')} – Agência {lv('agency')} – Prefixo {lv('prefix')}", st["body"]),
        Paragraph(f"<b>ENDEREÇO:</b> {lv('address')}", st["body"]),
        Paragraph(f"<b>DATA DA VISTORIA:</b> {lv('date')}", st["body"]),
        Spacer(1,3*mm), HRFlowable(width=CONTENT_W, thickness=0.5, color=LGRAY), Spacer(1,3*mm),
    ]
    ini = lv("initial_considerations") or ("O presente relatório técnico foi elaborado com base no Relatório Fotográfico. "
          "A vistoria identificou patologias construtivas relevantes, evidenciando falhas recorrentes de "
          "impermeabilização, intervenções paliativas e ausência de dispositivos de segurança.")
    story += [Paragraph("<b>1. CONSIDERAÇÕES INICIAIS</b>", st["tech_sec"]), Paragraph(ini, st["body"]), Spacer(1,3*mm)]

    for idx,sec in enumerate(tech, 2):
        story.append(Paragraph(f"<b>{idx}. {sec.get('title','').upper()}</b>", st["tech_sec"]))
        probs = [p for p in sec.get("problems",[]) if p]
        sols  = [s for s in sec.get("solutions",[]) if s]
        if probs:
            story.append(Paragraph("<b>Problemas Identificados</b>", st["tech_sub"]))
            for p in probs: story.append(Paragraph(f"• {p}", st["tech_item"]))
        if sols:
            story += [Spacer(1,2*mm), Paragraph("<b>Soluções Técnicas</b>", st["tech_sub"])]
            for s in sols: story.append(Paragraph(f"• {s}", st["tech_item"]))
        story.append(Spacer(1,4*mm))

    gen = lv("general_assessment") or ("A edificação apresenta sistema de cobertura e impermeabilização em estado crítico, "
          "com histórico evidente de intervenções paliativas. Recomenda-se a execução das soluções "
          "propostas de forma integrada, evitando reparos pontuais isolados.")
    story += [Paragraph(f"<b>{len(tech)+2}. AVALIAÇÃO GERAL</b>", st["tech_sec"]), Paragraph(gen, st["body"])]
    return story

# ── Generate PDF ───────────────────────────────────────────────────────────
def generate_pdf(payload):
    data   = payload.get("data", {})
    photos = payload.get("photos", [])
    tech   = payload.get("tech_sections", [])
    logo_r2d = payload.get("logo_r2d", "")
    logo_bb  = payload.get("logo_client", "")
    st = build_styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=MARGIN, bottomMargin=MARGIN)
    story = []
    story += build_cover(data, st, logo_r2d, logo_bb)
    story += build_info_summary(data, st, logo_r2d, logo_bb, photos, tech)
    story += build_dados(data, st, logo_r2d, logo_bb)
    story += build_photos(data, st, logo_r2d, logo_bb, photos)
    story += build_tech(data, st, logo_r2d, logo_bb, tech, len(photos))
    doc.build(story)
    buf.seek(0)
    return buf

# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/historico")
def historico():
    return render_template("historico.html")

@app.route("/api/generate", methods=["POST"])
def api_generate():
    try:
        payload = request.get_json(force=True)
        data    = payload.get("data", {})
        photos  = payload.get("photos", [])
        tech    = payload.get("tech_sections", [])

        pdf_buf = generate_pdf(payload)

        report_id = str(uuid.uuid4())[:8]
        filename  = f"{report_id}.pdf"
        pdf_path  = os.path.join(PDF_DIR, filename)

        with open(pdf_path, "wb") as f:
            f.write(pdf_buf.read())

        db = get_db()
        db.execute("""INSERT INTO reports
            (id,agency,prefix,os,contract,fiscal,date,address,created,pdf_path,n_photos,n_sections)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report_id,
             data.get("agency",""), data.get("prefix",""),
             data.get("os",""),     data.get("contract",""),
             data.get("fiscal",""), data.get("date",""),
             data.get("address",""),
             datetime.now().strftime("%d/%m/%Y %H:%M"),
             filename, len(photos), len(tech)))
        db.commit()

        return jsonify({"ok": True, "id": report_id})
    except Exception as e:
        import traceback
        return jsonify({"ok": False, "error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/api/download/<report_id>")
def api_download(report_id):
    db = get_db()
    row = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not row: abort(404)
    path = os.path.join(PDF_DIR, row["pdf_path"])
    if not os.path.exists(path): abort(404)
    fname = f"relatorio_{row['agency'] or 'obra'}_{row['os'] or row['id']}.pdf"
    return send_file(path, mimetype="application/pdf",
                     as_attachment=True, download_name=fname)

@app.route("/api/reports")
def api_reports():
    db = get_db()
    rows = db.execute("SELECT * FROM reports ORDER BY created DESC").fetchall()
    return jsonify([dict(r) for r in rows])

@app.route("/api/reports/<report_id>", methods=["DELETE"])
def api_delete(report_id):
    db = get_db()
    row = db.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if row:
        path = os.path.join(PDF_DIR, row["pdf_path"])
        if os.path.exists(path): os.remove(path)
        db.execute("DELETE FROM reports WHERE id=?", (report_id,))
        db.commit()
    return jsonify({"ok": True})


@app.route("/api/ia", methods=["POST"])
def api_ia():
    """Proxy para Anthropic API — evita CORS no browser."""
    import urllib.request, urllib.error
    try:
        payload = request.get_json(force=True)
        caps    = payload.get("captions", "")
        prompt  = (
            "Você é engenheiro civil especialista em patologias de edificações. "
            "Analise estas legendas de um relatório fotográfico de vistoria e gere "
            "um relatório técnico estruturado.\n\nLEGENDAS:\n" + caps +
            "\n\nResponda APENAS com JSON válido sem markdown:\n"
            '{"initial_considerations":"...","general_assessment":"...",'
            '"sections":[{"title":"Nome da Área","problems":["..."],"solutions":["..."]}]}'
        )
        body = json.dumps({
            "model": "claude-sonnet-4-5",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         os.environ.get("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
            }
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        text = next((c["text"] for c in data.get("content", []) if c["type"] == "text"), "{}")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text
            text = text.rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        return jsonify(parsed)
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()
        import traceback
        return jsonify({"error": f"Anthropic error {e.code}: {body_err}", "trace": traceback.format_exc()}), 500
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# Inicializa o banco ao carregar o módulo (funciona com gunicorn e direto)
with app.app_context():
    init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
