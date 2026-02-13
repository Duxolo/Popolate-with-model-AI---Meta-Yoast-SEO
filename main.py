import sys
import csv
import requests
import time
import re
import os

from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QPlainTextEdit, QLineEdit, QFileDialog, QLabel
)

# ---------------- CONFIG BASE ----------------
MODEL = "qwen2.5:3b-instruct"
OLLAMA_URL = "http://localhost:11434/api/generate"

# Indici di colonna IN INPUT (0-based)
COL_TITLE_IN = 4   # colonna E -> Titolo prodotto
COL_DESC_IN = 9    # colonna J -> Descrizione prodotto

# ✅ Nomi colonne Yoast (corretti)
YOAST_FOCUSKW_HEADER = "Meta: _yoast_wpseo_focuskw"
YOAST_TITLE_HEADER   = "Meta: _yoast_wpseo_title"
YOAST_DESC_HEADER    = "Meta: _yoast_wpseo_metadesc"
LONG_DESC_HEADER = "Descrizione"   # ✅ descrizione lunga WooCommerce (colonna CSV)


# Range desiderato per la meta description
MIN_DESC_LEN = 120
MAX_DESC_LEN = 150

BANNED_TOKENS = [
    "woocommerce",
    "WooCommerce",
    "WordPress",
    "wordpress",
    "scada24",
    "Scada24",
    "www.",
    "http://",
    "https://",
]

CTA_PHRASES = [
    "Scopri di più",
    "Acquista ora",
    "Ordina online",
]

STOPWORDS_IT = {
    "di","a","da","in","con","su","per","tra","fra",
    "e","ed",
    "il","lo","la","i","gli","le",
    "un","uno","una",
    "del","della","dei","degli","delle",
    "al","allo","alla","ai","agli","alle",
    "dal","dallo","dalla","dai","dagli","dalle",
    "nel","nello","nella","nei","negli","nelle",
    "col","coi","sul","sullo","sulla","sui","sugli","sulle"
}

# ---------------- UTIL ----------------

def ensure_len(row, min_len_index: int):
    if len(row) <= min_len_index:
        row.extend([""] * (min_len_index + 1 - len(row)))
    return row

def strip_quotes(text: str) -> str:
    if not text:
        return ""
    return (text
            .replace('"', "")
            .replace("“", "")
            .replace("”", "")
            .replace("’", "'")
            ).strip()

def remove_urls_and_domains(text: str) -> str:
    if not text:
        return ""
    out = text
    # url completi
    out = re.sub(r"\bhttps?://\S+\b", "", out, flags=re.I)
    out = re.sub(r"\bwww\.\S+\b", "", out, flags=re.I)
    # domini "nudi" tipo example.com / example.it
    out = re.sub(r"\b[^\s]+\.(it|com|net|org|eu|info|biz)\b", "", out, flags=re.I)
    return out

def clean_text(text: str) -> str:
    if not text:
        return ""
    out = strip_quotes(text)
    out = remove_urls_and_domains(out)

    for token in BANNED_TOKENS:
        out = out.replace(token, "")

    # ripulisci spazi
    out = re.sub(r"\s+", " ", out).strip()
    # pulizia punteggiatura “doppia” casuale
    out = re.sub(r"\s+([,;:.!?])", r"\1", out)
    out = re.sub(r"([,;:.!?]){2,}", r"\1", out)
    return out.strip()

def hard_trim(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text

    cut = text[:max_len]
    last_punct = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if last_punct != -1 and last_punct > max_len * 0.5:
        return cut[:last_punct + 1].rstrip()

    last_space = cut.rfind(" ")
    if last_space > 0:
        return cut[:last_space].rstrip()

    return cut.rstrip()

def limit_title_words(title: str, max_content_words: int = 4) -> str:
    """Riduce il title a max N parole di contenuto (Yoast-style)."""
    if not title:
        return ""
    words = title.split()
    content_count = 0
    result = []

    for w in words:
        clean = re.sub(r"[^\wàèéìòùÀÈÉÌÒÙ]", "", w.lower())
        if clean and clean not in STOPWORDS_IT:
            content_count += 1
        result.append(w)
        if content_count >= max_content_words:
            break

    return " ".join(result) if result else title

def derive_focuskw(nome: str, max_words: int = 4) -> str:
    """Deriva una focus keyphrase dal nome prodotto (max N parole 'di contenuto')."""
    nome = clean_text(nome or "")
    if not nome:
        return ""
    words = []
    for w in nome.split():
        c = re.sub(r"[^\wàèéìòùÀÈÉÌÒÙ]", "", w.lower())
        if c and c not in STOPWORDS_IT:
            words.append(w)
        if len(words) >= max_words:
            break
    return " ".join(words).strip()


def _norm(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"<[^>]+>", " ", s)   # ✅ rimuove html
    s = re.sub(r"\s+", " ", s).strip()
    return s


def ensure_keyphrase_in_title(title: str, keyphrase: str) -> str:
    title = clean_text(title or "")
    kp = clean_text(keyphrase or "")
    if not kp:
        return title
    if _norm(kp) in _norm(title):
        return title

    # Prepend keyphrase, poi rifila a 60
    merged = f"{kp} – {title}".strip(" –-")
    merged = hard_trim(merged, 60)
    return merged

def ensure_keyphrase_in_metadesc(desc: str, keyphrase: str) -> str:
    # desc arriva già “finalizzata”, ma noi garantiamo la presenza della keyphrase
    desc = finalize_description(desc or "")
    kp = clean_text(keyphrase or "")
    if not kp:
        return desc
    if _norm(kp) in _norm(desc):
        return desc

    # Metti keyphrase all'inizio e poi ri-finalizza (CTA, lunghezza, pulizia)
    base = remove_all_cta(desc)
    merged = f"{kp}: {base}".strip()
    merged = finalize_description(merged)
    return merged

def ensure_keyphrase_paragraph_at_start(long_desc: str, keyphrase: str) -> str:
    kp = clean_text(keyphrase or "").strip()
    if not kp:
        return (long_desc or "").strip()

    ld = (long_desc or "").lstrip()

    head = ld[:500]
    head_no_html = re.sub(r"<[^>]+>", " ", head)
    if _norm(kp) in _norm(head_no_html):
        return ld

    return f"<p>{kp}</p>\n{ld}".strip()



def remove_all_cta(desc: str) -> str:
    if not desc:
        return ""
    out = desc
    for phrase in CTA_PHRASES:
        out = out.replace(phrase, "")
    out = re.sub(r"\s+", " ", out).strip()
    # ripulisci separatori finali prima della CTA
    out = out.rstrip(" -–—,:;")
    return out.strip()

def ensure_single_cta_at_end(desc: str, cta: str = "Acquista ora") -> str:
    """Rimuove tutte le CTA e ne appende UNA sola alla fine."""
    base = remove_all_cta(desc)
    base = base.rstrip(" -–—,:;")
    if not base:
        return cta
    # se termina con punto, ok; altrimenti niente obbligo
    return f"{base} {cta}".strip()

def pad_to_min_len(desc: str) -> str:
    """Se troppo corta, aggiunge contenuto tecnico generico senza sforare MAX."""
    filler_chunks = [
        "Qualità professionale e affidabilità costante.",
        "Ideale per impianti e manutenzioni industriali.",
        "Materiali resistenti e prestazioni stabili nel tempo."
    ]
    out = desc
    idx = 0
    while len(out) < MIN_DESC_LEN and idx < len(filler_chunks):
        # inserisci il filler PRIMA della CTA finale
        for cta in CTA_PHRASES:
            if out.endswith(cta):
                base = out[:-len(cta)].rstrip()
                out = f"{base} {filler_chunks[idx]} {cta}".strip()
                break
        else:
            out = f"{out} {filler_chunks[idx]}".strip()
        out = re.sub(r"\s+", " ", out).strip()
        if len(out) > MAX_DESC_LEN:
            out = hard_trim(out, MAX_DESC_LEN)
            out = re.sub(r"\s+", " ", out).strip()
            break
        idx += 1
    return out

def finalize_description(desc: str) -> str:
    """Pulizia finale: niente url, niente doppi apici, CTA una sola in coda, trim e min length."""
    out = clean_text(desc or "")
    out = ensure_single_cta_at_end(out, cta="Acquista ora")
    if len(out) > MAX_DESC_LEN:
        out = hard_trim(out, MAX_DESC_LEN)
        out = ensure_single_cta_at_end(out, cta="Acquista ora")
        if len(out) > MAX_DESC_LEN:
            out = hard_trim(out, MAX_DESC_LEN)
    if len(out) < MIN_DESC_LEN:
        out = pad_to_min_len(out)
        if len(out) > MAX_DESC_LEN:
            out = hard_trim(out, MAX_DESC_LEN)
            out = ensure_single_cta_at_end(out, cta="Acquista ora")
            if len(out) > MAX_DESC_LEN:
                out = hard_trim(out, MAX_DESC_LEN)
    return out.strip()

def build_fallback_description(nome_prodotto: str) -> str:
    nome = (nome_prodotto or "").strip()
    if not nome:
        nome = "Componenti oleodinamici per impianti industriali"
    base = (
        f"{nome} per impianti oleodinamici e applicazioni meccaniche: "
        "prestazioni affidabili, materiali resistenti e uso professionale. Acquista ora"
    )
    return base

def enforce_meta_description_length(desc: str, nome_prodotto: str, logger=None) -> str:
    desc = clean_text(desc or "")
    desc = finalize_description(desc)

    if not desc:
        desc = build_fallback_description(nome_prodotto)
        return finalize_description(desc)

    if MIN_DESC_LEN <= len(desc) <= MAX_DESC_LEN:
        return desc

    # Riscrittura tramite modello (ma poi comunque applichiamo finalize_description)
    prompt = f"""
Sei uno specialista SEO per e-commerce B2B.

Devi RISCRIVERE la seguente meta description in italiano in modo che:
- sia compresa indicativamente tra 120 e 150 caratteri
- resti naturale e leggibile
- descriva il prodotto in modo specifico (uso, caratteristiche tecniche, vantaggi)
- includa UNA sola call to action breve ALLA FINE della frase
- NON ripeta più volte parole come "Scopri di più", "Acquista ora", "Ordina online"

VINCOLI:
- NON usare il carattere " (doppi apici) da nessuna parte nel testo.
- NON usare markdown.
- NON inserire URL o domini (niente www, .it, http, https).
- NON citare nomi di piattaforme o negozi (WooCommerce, WordPress, Scada24, ecc.).

NOME PRODOTTO:
\"\"\"{nome_prodotto}\"\"\" 

META DESCRIPTION ORIGINALE:
\"\"\"{desc}\"\"\" 

Rispondi SOLO con la nuova meta description, in UNA sola riga, senza prefissi tipo DESCRIPTION:.
"""

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 200,
            "temperature": 0.5,
        },
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=200)
        resp.raise_for_status()
        data = resp.json()
        new_raw = data.get("response", "").strip()
        new_desc = new_raw.splitlines()[0].strip() if new_raw else ""
        new_desc = finalize_description(new_desc)
    except Exception as e:
        msg = f"⚠ Errore durante riscrittura description per {nome_prodotto[:40]!r}: {e}"
        if logger:
            logger(msg)
        else:
            print(msg)
        # fallback “sicuro” anche qui
        return finalize_description(desc) if desc else finalize_description(build_fallback_description(nome_prodotto))

    if not new_desc:
        msg = f"⚠ Nessuna description valida ricevuta nel tentativo di riscrittura per {nome_prodotto[:40]!r}"
        if logger:
            logger(msg)
        else:
            print(msg)
        return finalize_description(desc) if desc else finalize_description(build_fallback_description(nome_prodotto))

    return new_desc

# TEMPLATE FISSO DEL PROMPT (NON EDITABILE DA GUI)
BASE_PROMPT = """Sei uno specialista SEO per e-commerce B2B.

Settore / categoria prodotti:
\"\"\"{settore}\"\"\" 

Devi generare:
- UN SEO title (max 60 caratteri) in italiano.
- UNA meta description (idealmente tra 120 e 150 caratteri) in italiano.

REQUISITI SEO TITLE:
- massimo 60 caratteri
- includi la parola chiave principale derivata dal nome prodotto
- chiaro, descrittivo e invogliante, senza frasi passive
- nessun nome di piattaforma o negozio (niente WooCommerce, WordPress, Scada24, ecc.)
- nessun URL o dominio (niente www, .it, http, https)

REQUISITI META DESCRIPTION:
- puntare a una lunghezza tra 120 e 150 caratteri
- includere la stessa parola chiave principale
- testo naturale e specifico per questo prodotto (caratteristiche tecniche, uso, vantaggi)
- UNA sola call to action breve ALLA FINE (es. Scopri di più, Acquista ora, Ordina online)
- NON ripetere più volte la stessa call to action
- nessun nome di piattaforma o negozio (niente WooCommerce, WordPress, Scada24, ecc.)
- nessun URL o dominio (niente www, .it, http, https)

CONTESTO PRODOTTO:
\"\"\"{contesto}\"\"\" 

FORMATO RISPOSTA (OBBLIGATORIO):
Rispondi esattamente con DUE righe:

TITLE: <SEO title qui, in una sola riga>
DESCRIPTION: <meta description qui, in una sola riga>

Non aggiungere altre righe, testo o simboli.
"""

def genera_meta(nome_prodotto: str, descrizione: str, prompt_template: str, logger=None):
    testo_nome = nome_prodotto.strip() if nome_prodotto else ""
    testo_desc = descrizione.strip() if descrizione else ""

    if not testo_nome and not testo_desc:
        return "", ""

    contesto = f"Nome prodotto: {testo_nome}\nDescrizione: {testo_desc}"
    prompt = prompt_template.format(contesto=contesto)

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": 200,
            "temperature": 0.6,
        },
    }

    start = time.time()
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=200)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        msg = f"⏱ Timeout da Ollama (>{200}s) per prodotto: {testo_nome[:40]!r}, salto questa riga."
        if logger: logger(msg)
        else: print(msg)
        return "", ""
    except Exception as e:
        msg = f"⚠ Errore chiamata Ollama per {testo_nome[:40]!r}: {e}"
        if logger: logger(msg)
        else: print(msg)
        return "", ""

    elapsed = time.time() - start
    msg = f"✅ Risposta Ollama in {elapsed:.1f} secondi per: {testo_nome[:40]!r}"
    if logger: logger(msg)
    else: print(msg)

    raw = (data.get("response", "") or "").strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    title = ""
    desc = ""

    for line in lines:
        m_title = re.search(r"^title\s*:\s*(.+)$", line, re.IGNORECASE)
        m_desc = re.search(r"^description\s*:\s*(.+)$", line, re.IGNORECASE)
        if m_title:
            title = m_title.group(1).strip()
        if m_desc:
            desc = m_desc.group(1).strip()

    if not title and not desc:
        msg = "⚠ Formato risposta inatteso, riga saltata."
        if logger:
            logger(msg)
            logger(raw[:300])
        else:
            print(msg)
            print(raw[:300])
        return "", ""

    title = clean_text(title)
    title = hard_trim(title, 60)
    title = limit_title_words(title, max_content_words=4)

    desc = enforce_meta_description_length(desc, testo_nome, logger=logger)

    return title, desc

class SeoWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, input_csv, output_csv, prompt_template, parent=None):
        super().__init__(parent)
        self.input_csv = input_csv
        self.output_csv = output_csv
        self.prompt_template = prompt_template
        self._stop = False

    def stop(self):
        self._stop = True

    def log(self, msg: str):
        self.log_signal.emit(msg)

    def run(self):
        try:
            with open(self.input_csv, "r", encoding="utf-8", newline="") as f_in:
                # ✅ Sniff delimitatore ; o ,
                sample = f_in.read(4096)
                f_in.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=";,")
                except Exception:
                    # fallback: molti export Woo sono ;
                    dialect = csv.excel
                    dialect.delimiter = ";"

                rows = list(csv.reader(f_in, dialect))

            if not rows:
                self.log("Nessuna riga trovata nel CSV.")
                self.finished_signal.emit("Nessuna riga da processare.")
                return

            header = rows[0]

            # ✅ trova/crea colonne Yoast
            def get_or_add(hname: str):
                try:
                    return header.index(hname)
                except ValueError:
                    header.append(hname)
                    return len(header) - 1

            yoast_focuskw_idx = get_or_add(YOAST_FOCUSKW_HEADER)
            yoast_title_idx   = get_or_add(YOAST_TITLE_HEADER)
            yoast_desc_idx    = get_or_add(YOAST_DESC_HEADER)

            # ✅ colonna descrizione lunga WooCommerce
            long_desc_idx     = get_or_add(LONG_DESC_HEADER)

            max_out_index = max(yoast_focuskw_idx, yoast_title_idx, yoast_desc_idx, long_desc_idx)


            # righe “vere”
            data_rows = [
                r for r in rows[1:]
                if any((c or "").strip() for c in r)
            ]

            total = len(data_rows)
            self.log(f"Totale righe da processare: {total}")
            self.log(f"Delimitatore rilevato: {getattr(dialect, 'delimiter', ';')!r}")

            with open(self.output_csv, "w", encoding="utf-8", newline="") as f_out:
                writer = csv.writer(
                    f_out,
                    delimiter=getattr(dialect, "delimiter", ";"),
                    quotechar=getattr(dialect, "quotechar", '"'),
                    quoting=csv.QUOTE_MINIMAL
                )

                writer.writerow(header)

                for i, row in enumerate(data_rows, start=1):
                    if self._stop:
                        self.log("⛔ Interrotto dall'utente.")
                        self.finished_signal.emit("Interrotto dall'utente.")
                        return

                    row = ensure_len(row, max_out_index)

                    nome = row[COL_TITLE_IN] if len(row) > COL_TITLE_IN else ""
                    descr = row[COL_DESC_IN] if len(row) > COL_DESC_IN else ""

                    title, desc = genera_meta(nome, descr, self.prompt_template, logger=self.log)

                    # ✅ focus keyphrase derivata dal nome prodotto
                    focuskw = derive_focuskw(nome)

                    # ✅ forza keyphrase dentro title + metadesc
                    title = ensure_keyphrase_in_title(title, focuskw)
                    desc  = ensure_keyphrase_in_metadesc(desc, focuskw)

                    row[yoast_focuskw_idx] = focuskw
                    row[yoast_title_idx]   = title
                    row[yoast_desc_idx]    = desc

                    # ✅ mette la keyphrase come primo paragrafo nella descrizione lunga
                    current_long_desc = row[long_desc_idx] if len(row) > long_desc_idx else ""
                    row[long_desc_idx] = ensure_keyphrase_paragraph_at_start(current_long_desc, focuskw)


                    writer.writerow(row)

                    if i % 10 == 0:
                        self.log(f"Righe processate: {i}/{total}")

            self.finished_signal.emit(f"Fatto. File generato: {self.output_csv}")

        except Exception as e:
            self.error_signal.emit(str(e))

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.worker = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("SEO Meta Generator - Luigi Serafino")

        layout = QVBoxLayout(self)

        file_layout = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Seleziona il CSV di input...")
        browse_btn = QPushButton("Sfoglia...")
        browse_btn.clicked.connect(self.choose_file)
        file_layout.addWidget(QLabel("CSV input:"))
        file_layout.addWidget(self.input_edit)
        file_layout.addWidget(browse_btn)
        layout.addLayout(file_layout)

        self.output_label = QLabel("Output: (verrà creato automaticamente)")
        layout.addWidget(self.output_label)

        layout.addWidget(QLabel("Settore / categoria prodotti (es: oli per trattori, raccordi DKOL, pistoni, ecc.):"))
        self.sector_edit = QPlainTextEdit()
        self.sector_edit.setPlainText("oleodinamica e meccanica industriale (raccordi, tubi, oli, componenti)")
        self.sector_edit.setMinimumHeight(80)
        layout.addWidget(self.sector_edit)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self.start_worker)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_worker)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        layout.addWidget(QLabel("Log:"))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #111; color: #0f0; font-family: Consolas, monospace;")
        layout.addWidget(self.log_view)

        self.resize(900, 700)

    def log(self, msg: str):
        self.log_view.appendPlainText(msg)
        self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Seleziona CSV di input", "", "CSV (*.csv);;Tutti i file (*.*)")
        if not path:
            return
        self.input_edit.setText(path)
        base, ext = os.path.splitext(path)
        out_path = base + "_con_meta.csv"
        self.output_label.setText(f"Output: {out_path}")

    def start_worker(self):
        input_csv = self.input_edit.text().strip()
        if not input_csv:
            self.log("⚠ Seleziona prima un CSV di input.")
            return
        if not os.path.exists(input_csv):
            self.log("⚠ Il file indicato non esiste.")
            return

        base, ext = os.path.splitext(input_csv)
        output_csv = base + "_con_meta.csv"

        settore = self.sector_edit.toPlainText().strip()
        if not settore:
            settore = "oleodinamica e componenti meccanici / industriali"

        prompt_template = BASE_PROMPT.format(settore=settore, contesto="{contesto}")

        self.log(f"▶ Avvio elaborazione su: {input_csv}")
        self.log(f"Output: {output_csv}")
        self.log(f"Settore/categoria: {settore}")

        self.worker = SeoWorker(input_csv, output_csv, prompt_template)
        self.worker.log_signal.connect(self.log)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.error_signal.connect(self.on_error)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.worker.start()

    def stop_worker(self):
        if self.worker is not None:
            self.worker.stop()
            self.log("Richiesta di stop inviata...")

    def on_finished(self, msg: str):
        self.log(f"✅ {msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None

    def on_error(self, msg: str):
        self.log(f"❌ Errore: {msg}")
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.worker = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
