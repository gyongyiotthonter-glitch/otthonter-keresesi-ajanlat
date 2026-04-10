import streamlit as st
import requests, re, os, io, shutil, tempfile
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                 TableStyle, Image as RLImage, HRFlowable, PageBreak)
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image as PILImage
import math

# ─── IRODAI ADATOK ────────────────────────────────────────────────────────────
IRODA = {
    "nev":      "OTTHONTÉR Ingatlaniroda",
    "szin_fo":  "#8B2635",   # bordó
    "szin_acc": "#8B2635",
    "szin_vilag": "#F5F0EE", # halvány krém háttér
}
BEVEZETO_ALAPSZOVEG = (
    "Egyeztetésünk és a megadott igények figyelembe vételével küldöm azokat "
    "ingatlanokat, amelyek célzott szűrésünk alapján megfelelhetnek az elvárásoknak.\n\n"
    "Amennyiben szívesen megnéznéd bármelyiket, kérlek jelezd és rugalmasan "
    "leszervezzük a bejárást."
)
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Ingatlan Keresési Ajánlat – OTTHONTÉR",
    page_icon="🏠", layout="centered"
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #faf8f6; }
.fejlec {
    background: #8B2635; color: white;
    padding: 1rem 1.5rem; border-radius: 10px; margin-bottom: 1.5rem;
}
.fejlec h1 { margin:0; font-size:1.4rem; letter-spacing:.05em; }
.fejlec p  { margin:0; font-size:.8rem; opacity:.75; margin-top:.2rem; }
.prop-ok  { background:#fff; border:1.5px solid #8B2635; border-radius:8px;
            padding:.7rem 1rem; margin-bottom:.4rem; }
.prop-err { background:#fff5f5; border:1.5px solid #ccc; border-radius:8px;
            padding:.7rem 1rem; margin-bottom:.4rem; color:#888; }
.prop-nev { font-weight:700; color:#8B2635; }
.prop-ar  { color:#8B2635; font-weight:700; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="fejlec">
  <h1>🏠 OTTHONTÉR — Ingatlan Keresési Ajánlat Generátor</h1>
  <p>Töltsd ki az adatokat, add meg a hirdetések linkjeit, majd generáld le a PDF ajánlatot.</p>
</div>
""", unsafe_allow_html=True)

# ── Segédfüggvények ────────────────────────────────────────────────────────────

def extract_id(url):
    m = re.search(r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', url)
    return m.group(1) if m else None

@st.cache_data(show_spinner=False)
def fetch_property(prop_id):
    try:
        r = requests.get(
            f"https://www.ingatlanbazar.hu/api/property/{prop_id}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.ingatlanbazar.hu/"},
            timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def download_images(prop_id, media_data, tmpdir, max_imgs=6):
    base = (f"https://content.ingatlanbazar.hu/static/property/images/"
            f"{prop_id[0:2]}/{prop_id[2:4]}/{prop_id[4:6]}/{prop_id[6:8]}/{prop_id}")
    paths = []
    for i, (img_id, _) in enumerate(list(media_data.items())[:max_imgs]):
        url = f"{base}/{img_id}_1024x768b.jpg"
        out = os.path.join(tmpdir, f"img_{i:02d}.jpg")
        try:
            r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code == 200 and len(r.content) > 5000:
                with open(out, 'wb') as f:
                    f.write(r.content)
                paths.append(out)
        except Exception:
            pass
    return paths

def get_sf(serialized, group_name):
    for f in serialized:
        if f.get('groupName') == group_name:
            return f.get('fieldName', '') or ''
    return ''

def fmt_price(p):
    try:
        return f"{int(p):,}".replace(',', ' ') + ' Ft'
    except Exception:
        return str(p) if p else '–'

def fmt_m2(v):
    return f"{v} m²" if v else '–'

@st.cache_resource
def reg_fonts():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
    ]
    if all(os.path.exists(p) for p in candidates):
        pdfmetrics.registerFont(TTFont('DV',     candidates[0]))
        pdfmetrics.registerFont(TTFont('DV-B',   candidates[1]))
        pdfmetrics.registerFont(TTFont('DV-I',   candidates[2]))
        return 'DV', 'DV-B', 'DV-I'
    return 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'

FREG, FBOLD, FITAL = reg_fonts()

# ── PDF generátor ──────────────────────────────────────────────────────────────

def build_pdf(properties, kuldo_nev, kuldo_tel, kuldo_email,
              ugyfel_nev, bevezeto):

    BORD   = colors.HexColor('#8B2635')
    KREM   = colors.HexColor('#F5F0EE')
    SZURKE = colors.HexColor('#6B6B6B')
    VILAG  = colors.HexColor('#FAFAFA')
    FEHER  = colors.white
    MID    = colors.HexColor('#D0C8C4')
    SOTET  = colors.HexColor('#2C2C2C')

    W, H = A4
    ML = MR = 1.6*cm
    MT = 1.4*cm
    MB = 1.4*cm
    CW = W - ML - MR

    def S(nm, **kw):
        d = dict(fontName=FREG, fontSize=10, leading=14, textColor=SOTET)
        d.update(kw)
        return ParagraphStyle(nm, **d)

    # Stílusok
    s_cim     = S('cim',  fontName=FBOLD, fontSize=22, textColor=BORD,  leading=28, alignment=TA_LEFT)
    s_alcim   = S('alcim',fontName=FREG,  fontSize=10, textColor=SZURKE,leading=14)
    s_fejlec  = S('fej',  fontName=FBOLD, fontSize=8,  textColor=FEHER, leading=12, alignment=TA_CENTER)
    s_lbl     = S('lbl',  fontName=FBOLD, fontSize=8.5,textColor=SZURKE,leading=12)
    s_val     = S('val',  fontName=FBOLD, fontSize=9,  textColor=SOTET, leading=13)
    s_ar      = S('ar',   fontName=FBOLD, fontSize=11, textColor=BORD,  leading=15)
    s_body    = S('bdy',  fontName=FREG,  fontSize=9.5,leading=14, alignment=TA_JUSTIFY, textColor=SOTET)
    s_bev     = S('bev',  fontName=FREG,  fontSize=9,  leading=14, textColor=SOTET)
    s_labléc  = S('lab',  fontName=FREG,  fontSize=7.5,textColor=SZURKE,alignment=TA_CENTER)
    s_ingatlan_cim = S('ict', fontName=FBOLD, fontSize=16, textColor=BORD, leading=22)
    s_th      = S('th',   fontName=FBOLD, fontSize=8,  textColor=FEHER, leading=12)
    s_td      = S('td',   fontName=FREG,  fontSize=9,  textColor=SOTET, leading=13)
    s_td_ar   = S('tda',  fontName=FBOLD, fontSize=8,  textColor=BORD,  leading=12)
    s_kuldo   = S('kld',  fontName=FREG,  fontSize=8.5,textColor=SOTET, leading=13)
    s_kuldo_b = S('kldb', fontName=FBOLD, fontSize=8.5,textColor=SOTET, leading=13)

    def lap_lablec(canvas, doc):
        canvas.saveState()
        canvas.setFont(FREG, 7.5)
        canvas.setFillColor(SZURKE)
        canvas.drawString(ML, 0.8*cm, "Otthontér")
        canvas.drawRightString(W - MR, 0.8*cm, str(doc.page))
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=ML, rightMargin=MR,
                            topMargin=MT, bottomMargin=MB,
                            onPage=lap_lablec, onLaterPages=lap_lablec)
    story = []

    # ══ 1. OLDAL: FEDŐLAP ══════════════════════════════════════════════════════

    # Logó helyett stilizált szöveges fejléc
    logo_path = os.path.join(os.path.dirname(__file__), 'logo_otthonter.png')
    if os.path.exists(logo_path):
        try:
            with PILImage.open(logo_path) as lim:
                lw, lh = lim.size
            logo_h = 1.5*cm
            logo_w = logo_h * (lw / lh)
            logo_img = RLImage(logo_path, width=logo_w, height=logo_h)
            logo_tbl = Table([[logo_img]], colWidths=[CW])
        except Exception:
            logo_tbl = Table([[Paragraph('⌂  OTTHONTÉR', S('lg', fontName=FBOLD, fontSize=14, textColor=BORD, leading=18))]], colWidths=[CW])
    else:
        logo_tbl = Table([[Paragraph('⌂  OTTHONTÉR', S('lg', fontName=FBOLD, fontSize=14, textColor=BORD, leading=18))]], colWidths=[CW])
    logo_tbl.setStyle(TableStyle([
        ('BOTTOMPADDING',(0,0),(-1,-1), 2),
        ('TOPPADDING',(0,0),(-1,-1), 2),
    ]))
    story.append(logo_tbl)
    story.append(HRFlowable(width=CW, thickness=1.5, color=BORD))
    story.append(Spacer(1, 8*mm))

    story.append(Paragraph('INGATLAN KERESÉSI', s_cim))
    story.append(Paragraph('AJÁNLAT', S('cim2', fontName=FBOLD, fontSize=22,
                                         textColor=BORD, leading=28)))
    story.append(Spacer(1, 6*mm))

    # Küldi / Címzett sor
    cimzett_str= f"<b>Címzett:</b> {ugyfel_nev or '–'}"
    kuldo_str  = f"<b>Küldi:</b> {kuldo_nev or '–'}   {kuldo_tel or ''}   {kuldo_email or ''}"
    kc_tbl = Table([[Paragraph(cimzett_str, s_kuldo), Paragraph(kuldo_str, s_kuldo)]],
                   colWidths=[CW*0.55, CW*0.45])
    kc_tbl.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5, MID),
        ('LINEAFTER',(0,0),(0,-1),0.5, MID),
        ('BACKGROUND',(0,0),(-1,-1), KREM),
        ('LEFTPADDING',(0,0),(-1,-1),7),
        ('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),6),
        ('BOTTOMPADDING',(0,0),(-1,-1),6),
    ]))
    story.append(kc_tbl)
    story.append(Spacer(1, 6*mm))

    # Bevezető szöveg
    bev_lines = bevezeto.replace('\r\n','\n').replace('\r','\n')
    bev_html = bev_lines.replace('\n','<br/>')
    bev_tbl = Table([[Paragraph(bev_html, s_bev)]], colWidths=[CW])
    bev_tbl.setStyle(TableStyle([
        ('BOX',(0,0),(-1,-1),0.5, MID),
        ('BACKGROUND',(0,0),(-1,-1), KREM),
        ('LEFTPADDING',(0,0),(-1,-1),10),
        ('RIGHTPADDING',(0,0),(-1,-1),10),
        ('TOPPADDING',(0,0),(-1,-1),8),
        ('BOTTOMPADDING',(0,0),(-1,-1),8),
    ]))
    story.append(bev_tbl)
    story.append(Spacer(1, 6*mm))

    # Összesítő táblázat
    story.append(HRFlowable(width=CW, thickness=0.5, color=MID))
    story.append(Spacer(1, 2*mm))
    osszesito_fejlec = [
        Paragraph('Helyszín', s_th),
        Paragraph('Típus', s_th),
        Paragraph('Alapterület (m²)', s_th),
        Paragraph('Telek (m²)', s_th),
        Paragraph('Szobák', s_th),
        Paragraph('Ár (Ft)', s_th),
    ]
    oss_rows = [osszesito_fejlec]
    for i, prop in enumerate(properties, 1):
        p  = prop['data']
        sf = p.get('serializedFields', [])
        q = (p.get('quarter') or '').strip()
        s = (p.get('settlement') or '').strip()
        helyszin = f'{q}, {s}' if q else s
        tipus    = get_sf(sf,'Ház típusa') or get_sf(sf,'Ingatlan típusa') or '–'
        oss_rows.append([
            Paragraph(helyszin, s_td),
            Paragraph(tipus, s_td),
            Paragraph(fmt_m2(p.get('area','')), s_td),
            Paragraph(fmt_m2(p.get('buildingSiteArea','')), s_td),
            Paragraph(str(p.get('roomsText', p.get('rooms','–'))), s_td),
            Paragraph(fmt_price(p.get('priceHUF',0)), s_td_ar),
        ])
    CW6 = [CW*0.30, CW*0.16, CW*0.12, CW*0.12, CW*0.10, CW*0.20]
    oss_tbl = Table(oss_rows, colWidths=CW6)
    oss_tbl.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0), BORD),
        ('ROWBACKGROUNDS',(0,1),(-1,-1), [FEHER, KREM]),
        ('GRID',(0,0),(-1,-1), 0.3, MID),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('LEFTPADDING',(0,0),(-1,-1),4),
        ('RIGHTPADDING',(0,0),(-1,-1),4),
        ('TOPPADDING',(0,0),(-1,-1),3),
        ('BOTTOMPADDING',(0,0),(-1,-1),3),
    ]))
    story.append(oss_tbl)

    # ══ INGATLANONKÉNTI OLDALAK ════════════════════════════════════════════════

    for idx, prop in enumerate(properties, 1):
        story.append(PageBreak())
        p    = prop['data']
        sf   = p.get('serializedFields', [])
        imgs = prop['images']
        desc = prop.get('desc_edit', '') or (p.get('description') or '')

        ingatlan_cim = f"{idx}. javasolt ingatlan"
        q = (p.get('quarter') or '').strip()
        s = (p.get('settlement') or '').strip()
        helyszin = f'{q}, {s}' if q else s

        # Fejléc
        story.append(Paragraph(ingatlan_cim, s_ingatlan_cim))
        story.append(Paragraph(helyszin, S('hlsz', fontName=FBOLD, fontSize=13, textColor=SOTET, leading=18)))
        story.append(Spacer(1, 3*mm))
        story.append(HRFlowable(width=CW, thickness=1, color=BORD))
        story.append(Spacer(1, 4*mm))

        # ── Adattábla bal + Leírás jobb ──────────────────────────────────────
        adat_mezok = [
            ('Alapterület',  fmt_m2(p.get('area',''))),
            ('Szobák',       str(p.get('roomsText', p.get('rooms','–')))),
            ('Ár',           fmt_price(p.get('priceHUF',0))),
            ('Állapot',      get_sf(sf,'Ingatlan állapot') or '–'),
            ('Kert / Telek', fmt_m2(p.get('buildingSiteArea',''))),
            ('Fűtés',        get_sf(sf,'Fűtés típusa') or '–'),
            ('Emelet',       get_sf(sf,'Emelet') or '–'),
            ('Tájolás',      get_sf(sf,'Tájolás') or '–'),
            ('Nm² ár',       fmt_price(p.get('sqmPriceHuf',0)).replace(' Ft',' Ft/m²') if p.get('sqmPriceHuf') else '–'),
        ]
        # Adattábla – teljes szélességben, 3 oszlopos: label | érték | label | érték | label | érték
        adat_sorok_full = []
        cols_adat = 3   # hány adat kerüljön egy sorba (label+érték párok)
        for row_i in range(0, len(adat_mezok), cols_adat):
            chunk = adat_mezok[row_i:row_i+cols_adat]
            while len(chunk) < cols_adat:
                chunk.append(('', ''))
            row_cells = []
            for k, v in chunk:
                row_cells.append(Paragraph(k, s_lbl))
                row_cells.append(Paragraph(v, s_val))
            adat_sorok_full.append(row_cells)

        col_unit = CW / (cols_adat * 2)
        adat_col_widths = [col_unit * 0.85, col_unit * 1.15] * cols_adat
        adat_tbl = Table(adat_sorok_full, colWidths=adat_col_widths)
        adat_tbl.setStyle(TableStyle([
            ('ROWBACKGROUNDS',(0,0),(-1,-1),[FEHER, KREM]),
            ('LINEBELOW',(0,0),(-1,-2),0.3, MID),
            ('LEFTPADDING',(0,0),(-1,-1),5),
            ('RIGHTPADDING',(0,0),(-1,-1),5),
            ('TOPPADDING',(0,0),(-1,-1),4),
            ('BOTTOMPADDING',(0,0),(-1,-1),4),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('BOX',(0,0),(-1,-1),0.4, MID),
        ]))
        story.append(adat_tbl)
        story.append(Spacer(1, 4*mm))

        # Leírás – teljes szélességben
        desc_clean = desc.replace('\n','<br/>')
        leiras_tbl = Table([[Paragraph(desc_clean, s_body)]], colWidths=[CW])
        leiras_tbl.setStyle(TableStyle([
            ('BOX',(0,0),(-1,-1),0.4, MID),
            ('BACKGROUND',(0,0),(-1,-1), KREM),
            ('LEFTPADDING',(0,0),(-1,-1),8),
            ('RIGHTPADDING',(0,0),(-1,-1),8),
            ('TOPPADDING',(0,0),(-1,-1),7),
            ('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('VALIGN',(0,0),(-1,-1),'TOP'),
        ]))
        story.append(leiras_tbl)
        story.append(Spacer(1, 5*mm))

        # ── Fotógaléria (max 6 kép, aránymegtartással) ──────────────────────
        if imgs:
            story.append(HRFlowable(width=CW, thickness=0.4, color=MID))
            story.append(Spacer(1, 3*mm))
            GAP = 5*mm
            n      = min(len(imgs), 6)
            cols_n = 2
            rows_n = math.ceil(n / cols_n)
            iw = (CW - (cols_n-1)*GAP) / cols_n
            ih = iw * 0.72

            foto_rows = []
            for r in range(rows_n):
                row = []
                for c in range(cols_n):
                    idx2 = r*cols_n + c
                    if idx2 < n:
                        img_path = imgs[idx2]
                        # Aránymegtartás: lekérjük a valódi méretet
                        try:
                            with PILImage.open(img_path) as im:
                                orig_w, orig_h = im.size
                            ratio = orig_h / orig_w if orig_w else 0.75
                            actual_h = iw * ratio
                            actual_h = min(actual_h, ih * 1.3)
                        except Exception:
                            actual_h = ih
                        row.append(RLImage(img_path, width=iw, height=actual_h))
                    else:
                        row.append('')
                foto_rows.append(row)

            foto_tbl = Table(foto_rows,
                             colWidths=[iw]*cols_n,
                             rowHeights=None)
            foto_tbl.setStyle(TableStyle([
                ('LEFTPADDING',(0,0),(-1,-1),GAP/2),
                ('RIGHTPADDING',(0,0),(-1,-1),GAP/2),
                ('TOPPADDING',(0,0),(-1,-1),GAP/2),
                ('BOTTOMPADDING',(0,0),(-1,-1),GAP/2),
                ('ALIGN',(0,0),(-1,-1),'CENTER'),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ]))
            story.append(foto_tbl)

    doc.build(story, onFirstPage=lap_lablec, onLaterPages=lap_lablec)
    return buf.getvalue()


# ══ STREAMLIT FELÜLET ══════════════════════════════════════════════════════════

# 1. Küldő adatai
st.subheader("📨 Küldő adatai")
c1,c2,c3 = st.columns(3)
with c1: kuldo_nev   = st.text_input("Küldő neve",    placeholder="pl. Takács Adél")
with c2: kuldo_tel   = st.text_input("Telefon",        placeholder="pl. +36 30 600 9530")
with c3: kuldo_email = st.text_input("E-mail",         placeholder="pl. adel@otthonter.hu")

# 2. Ügyfél
st.subheader("👤 Ügyfél neve")
ugyfel_nev = st.text_input("Ügyfél neve", placeholder="pl. Kovács László", label_visibility="collapsed")

# 3. Bevezető szöveg
st.subheader("✉️ Bevezető szöveg")
st.caption("Előre kitöltve, de szabadon szerkeszthető.")
bevezeto = st.text_area("Bevezető", value=BEVEZETO_ALAPSZOVEG, height=300, label_visibility="collapsed")

# 4. Ingatlanok
st.subheader("🔗 Ingatlanbazar.hu hirdetések")
st.caption("Add meg a hirdetések linkjeit. Annyi ingatlan adható hozzá, amennyit szeretnél.")

if "url_list"  not in st.session_state: st.session_state.url_list  = [""]
if "desc_list" not in st.session_state: st.session_state.desc_list = [""]

for i in range(len(st.session_state.url_list)):
    url = st.session_state.url_list[i]
    col_url, col_del = st.columns([0.92, 0.08])
    with col_url:
        new_url = st.text_input(
            f"Ingatlan #{i+1} URL", value=url,
            placeholder="https://www.ingatlanbazar.hu/...",
            key=f"url_{i}", label_visibility="collapsed")
        st.session_state.url_list[i] = new_url

        if new_url and len(new_url) > 30:
            pid = extract_id(new_url)
            if pid:
                with st.spinner("Adatok letöltése..."):
                    data = fetch_property(pid)
                if data:
                    p = data['property']
                    st.markdown(
                        f'<div class="prop-ok">'
                        f'<span class="prop-nev">✅ {p.get("quarter","")}, {p.get("settlement","")}</span>'
                        f'&nbsp;&nbsp;🏠 {p.get("area","–")} m²'
                        f'&nbsp;&nbsp;🛏 {p.get("roomsText", p.get("rooms","–"))} szoba'
                        f'&nbsp;&nbsp;<span class="prop-ar">{fmt_price(p.get("priceHUF",0))}</span>'
                        f'</div>', unsafe_allow_html=True)

                    # Szerkeszthető leírás mező
                    while len(st.session_state.desc_list) <= i:
                        st.session_state.desc_list.append("")
                    if not st.session_state.desc_list[i]:
                        st.session_state.desc_list[i] = (p.get('description') or '')[:1200]
                    st.session_state.desc_list[i] = st.text_area(
                        f"Szöveges leírás #{i+1} (szerkeszthető)",
                        value=st.session_state.desc_list[i],
                        height=260, key=f"desc_{i}")
                else:
                    st.markdown('<div class="prop-err">❌ Nem sikerült letölteni. Ellenőrizd az URL-t!</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="prop-err">⚠️ Nem ingatlanbazar.hu link.</div>', unsafe_allow_html=True)

    with col_del:
        if i > 0:
            if st.button("✕", key=f"del_{i}"):
                st.session_state.url_list.pop(i)
                st.session_state.desc_list.pop(i) if i < len(st.session_state.desc_list) else None
                st.rerun()

if st.button("➕  Újabb ingatlan hozzáadása", use_container_width=True):
    st.session_state.url_list.append("")
    st.session_state.desc_list.append("")
    st.rerun()

st.divider()

# ── Generálás ──────────────────────────────────────────────────────────────────
if st.button("📄  PDF Ajánlat Generálása", type="primary", use_container_width=True):
    valid = [(u, st.session_state.desc_list[i] if i < len(st.session_state.desc_list) else "")
             for i, u in enumerate(st.session_state.url_list)
             if u.strip() and extract_id(u)]
    if not valid:
        st.error("Adj meg legalább egy érvényes ingatlanbazar.hu URL-t!")
    else:
        tmpdir = tempfile.mkdtemp()
        try:
            properties = []
            prog = st.progress(0, text="Adatok letöltése...")
            for i, (url, desc_edit) in enumerate(valid):
                prog.progress((i+1)/len(valid), text=f"Ingatlan {i+1}/{len(valid)}...")
                pid  = extract_id(url)
                data = fetch_property(pid)
                if not data: continue
                p      = data['property']
                media  = p.get('mediaData', {})
                imgdir = os.path.join(tmpdir, f"p{i}")
                os.makedirs(imgdir, exist_ok=True)
                imgs = download_images(pid, media, imgdir, max_imgs=6)
                properties.append({'data': p, 'images': imgs, 'desc_edit': desc_edit})

            if not properties:
                st.error("Nem sikerült egyetlen ingatlan adatait sem letölteni!")
            else:
                prog.progress(1.0, text="PDF generálása...")
                pdf = build_pdf(properties, kuldo_nev, kuldo_tel, kuldo_email,
                                ugyfel_nev, bevezeto)
                safe = (ugyfel_nev or 'ajanlat').replace(' ','_')
                fn   = f"OtthonTer_{safe}_{date.today().strftime('%Y%m%d')}.pdf"
                prog.empty()
                st.success(f"✅ PDF kész! ({len(properties)} ingatlan · {len(pdf)//1024} KB)")
                st.download_button("⬇️  PDF Letöltése", data=pdf,
                                   file_name=fn, mime="application/pdf",
                                   use_container_width=True)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

st.markdown("---")
st.caption("OTTHONTÉR Ingatlaniroda")
