import threading
import time
import random
import re
import unicodedata
from pathlib import Path
from datetime import datetime
import csv
import webbrowser

import requests
import tkinter as tk
from tkinter import filedialog, messagebox
from openpyxl import Workbook


# ---------------- Config ----------------
RETRY_STATUS = {429, 502, 503, 504}
DEFAULT_BASE_URL = "https://api.webdoxclm.com/api/v2"


# ---------------- Paleta ----------------
PRIMARY      = "#1F3A5F"
PRIMARY_2    = "#2E5B9A"
ACCENT       = "#3B82F6"
WHITE        = "#FFFFFF"
BG_MAIN      = "#F7F9FC"
BG_CARD      = "#FFFFFF"
BORDER       = "#D9E2F0"
TEXT_MAIN    = "#243447"
TEXT_SOFT    = "#6B7280"
TEXT_DARK    = "#111827"
SUCCESS      = "#15803D"
DANGER       = "#DC2626"
WARNING      = "#D97706"
INFO_BG      = "#EFF6FF"
SHADOW_COLOR = "#DCE6F4"


# ---------------- RateLimiter ----------------
class RateLimiter:
    def __init__(self, max_per_minute=59):
        self.min_interval = 60.0 / max_per_minute
        self.last = 0.0
        self.lock = threading.Lock()

    def wait(self):
        with self.lock:
            now = time.time()
            elapsed = now - self.last
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last = time.time()


# ---------------- Cancel ----------------
class Cancelled(Exception):
    pass


# ---------------- Helpers ----------------
def safe_filename(name: str) -> str:
    name = (name or "").strip().replace("\n", " ")
    name = re.sub(r'[\\/:*?"<>|]+', "_", name)
    return name[:180] if len(name) > 180 else (name or "arquivo")


def garantir_ext(nome: str, file_ext) -> str:
    if "." in Path(nome).name:
        return nome
    if file_ext:
        return f"{nome}.{file_ext}"
    return nome


def normalize_key(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.upper()
    s = re.sub(r"[^A-Z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def matches_search_terms(nome: str, termos_incluir: list[str]) -> bool:
    nome_norm = normalize_key(nome)
    if not termos_incluir:
        return True
    return any(t in nome_norm for t in termos_incluir)


def matches_suffix(nome: str, suffix: str) -> bool:
    suffix = (suffix or "").strip()
    if not suffix:
        return True
    return nome.strip().lower().endswith(suffix.lower())


def eh_documento_alvo(nome: str, termos_incluir: list[str], suffix: str) -> bool:
    return matches_search_terms(nome, termos_incluir) and matches_suffix(nome, suffix)


# ---------------- CSV helpers ----------------
def read_workflow_ids(csv_path: str) -> list:
    ids = []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if "workflow_id" not in (reader.fieldnames or []):
            raise RuntimeError("O CSV precisa conter a coluna 'workflow_id'.")
        for row in reader:
            w = (row.get("workflow_id") or "").strip()
            if w:
                ids.append(w)
    return ids


def write_report_xlsx(out_path: Path, rows: list):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fields = ["workflow_id", "workflow_name", "docs_encontrados", "docs_baixados"]

    wb = Workbook()
    ws = wb.active
    ws.title = "Relatorio"

    ws.append(fields)

    for r in rows:
        ws.append([r.get(k, "") for k in fields])

    widths = {"A": 18, "B": 50, "C": 18, "D": 18}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width

    wb.save(out_path)


# ---------------- PDF Merge ----------------
def merge_pdfs(pdf_paths: list, out_pdf: Path) -> bool:
    pdf_paths = [p for p in pdf_paths if p.exists() and p.suffix.lower() == ".pdf"]
    if not pdf_paths:
        return False

    from pypdf import PdfWriter
    writer = PdfWriter()

    for p in pdf_paths:
        writer.append(str(p))

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as f:
        writer.write(f)

    return True


# ---------------- Webdox Client ----------------
class WebdoxClient:
    def __init__(self, base_url: str, username: str, password: str, ambiente: str, log_fn, stop_event: threading.Event):
        self.base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        self.username = username.strip()
        self.password = password
        self.customer = (ambiente or "").strip()
        self.log = log_fn
        self.stop_event = stop_event
        self.sess = requests.Session()
        self.rate = RateLimiter(max_per_minute=59)
        self._auth = {
            "access_token": None,
            "refresh_token": None,
            "obtained_at": None,
            "expires_in": 7200
        }

    def _check_cancel(self):
        if self.stop_event.is_set():
            raise Cancelled("Operação cancelada pelo usuário.")

    def login(self):
        self._check_cancel()
        url = f"{self.base_url}/oauth/token"

        payload = {
            "username": self.username,
            "grant_type": "password",
            "password": self.password
        }
        if self.customer:
            payload["customer"] = self.customer

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        self.rate.wait()
        r = self.sess.post(url, data=payload, headers=headers, timeout=60)

        if r.status_code != 200:
            self.log(f"ERRO | Login status: {r.status_code}")
            self.log(f"ERRO | Resposta: {r.text[:800]}")
            r.raise_for_status()

        data = r.json()
        self._auth["access_token"] = data.get("access_token")
        self._auth["refresh_token"] = data.get("refresh_token")
        self._auth["expires_in"] = int(data.get("expires_in", 7200))
        self._auth["obtained_at"] = datetime.utcnow()

        self.sess.headers.update({"Authorization": f"Bearer {self._auth['access_token']}"})
        self.log("OK | Autenticação realizada com sucesso.")

    def refresh_token(self):
        self._check_cancel()

        if not self._auth.get("refresh_token"):
            raise RuntimeError("Sem refresh_token disponível. Faça login novamente.")

        url = f"{self.base_url}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._auth["refresh_token"]
        }
        if self.customer:
            payload["customer"] = self.customer

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        self.rate.wait()
        r = self.sess.post(url, data=payload, headers=headers, timeout=60)

        if r.status_code != 200:
            raise RuntimeError(f"Refresh falhou: {r.status_code} | {r.text[:300]}")

        data = r.json()
        self._auth["access_token"] = data.get("access_token")
        self._auth["refresh_token"] = data.get("refresh_token", self._auth["refresh_token"])
        self._auth["expires_in"] = int(data.get("expires_in", self._auth["expires_in"]))
        self._auth["obtained_at"] = datetime.utcnow()

        self.sess.headers.update({"Authorization": f"Bearer {self._auth['access_token']}"})
        self.log("INFO | Token renovado via refresh_token.")

    def request_with_retry(self, method: str, url: str, *, timeout=120, max_tries=6, stream=False, **kwargs):
        last = None
        refreshed_once = False

        for attempt in range(1, max_tries + 1):
            self._check_cancel()
            try:
                self.rate.wait()
                r = self.sess.request(method, url, timeout=timeout, stream=stream, **kwargs)
                last = r

                if r.status_code == 401 and not refreshed_once:
                    refreshed_once = True
                    try:
                        self.refresh_token()
                    except Exception:
                        self.log("AVISO | Refresh falhou, tentando novo login...")
                        self.login()

                    self.rate.wait()
                    r = self.sess.request(method, url, timeout=timeout, stream=stream, **kwargs)
                    last = r

                if r.status_code not in RETRY_STATUS:
                    return r

                retry_after = r.headers.get("Retry-After")
                try:
                    sleep_s = float(retry_after) if retry_after else None
                except Exception:
                    sleep_s = None

                if sleep_s is None:
                    sleep_s = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.8)

                self.log(f"AGUARD | HTTP {r.status_code} — tentativa {attempt}/{max_tries} — {sleep_s:.1f}s")
                time.sleep(sleep_s)

            except requests.RequestException as e:
                sleep_s = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.8)
                self.log(f"REDE | Erro ({e}) — tentativa {attempt}/{max_tries} — {sleep_s:.1f}s")
                time.sleep(sleep_s)

        return last

    def listar_docs_workflow(self, workflow_id: str):
        url = f"{self.base_url}/decision_workflows/{workflow_id}/documents"
        r = self.request_with_retry("GET", url, timeout=120, max_tries=6)

        if r is None:
            return None, ("REDE", "Falha de rede sem resposta")
        if r.status_code != 200:
            return None, (r.status_code, (r.text or "")[:800])

        return r.json(), None

    def get_workflow_info(self, workflow_id: str):
        url = f"{self.base_url}/decision_workflows/{workflow_id}"
        r = self.request_with_retry("GET", url, timeout=120, max_tries=6)
        if r is None or r.status_code != 200:
            return None
        return r.json()

    def get_document_meta(self, doc_id: str):
        url = f"{self.base_url}/documents/{doc_id}"
        r = self.request_with_retry("GET", url, timeout=120, max_tries=6)
        if r is None or r.status_code != 200:
            return None
        return r.json()

    def _pick_name_from_docs_item(self, item: dict):
        for k in ("name", "filename", "file_name", "attachment_file_name", "title", "subject_name"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def normalizar_docs(self, docs_raw):
        out = []
        for d in docs_raw:
            if isinstance(d, dict) and "download_url" in d:
                out.append({
                    "doc_id": str(d.get("id")),
                    "download_url": d.get("download_url"),
                    "nome_hint": self._pick_name_from_docs_item(d)
                })
            elif isinstance(d, dict) and len(d) == 1:
                doc_id, url = next(iter(d.items()))
                out.append({
                    "doc_id": str(doc_id),
                    "download_url": url,
                    "nome_hint": None
                })
        return out

    def escolher_nome(self, doc_id: str, nome_hint):
        if nome_hint:
            return nome_hint

        meta = self.get_document_meta(doc_id)
        if not meta:
            return f"doc_{doc_id}.pdf"

        ext = meta.get("file_ext") or meta.get("extension") or meta.get("ext") or "pdf"

        for k in ("name", "filename", "attachment_file_name", "file_name", "subject_name", "title"):
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                return garantir_ext(v.strip(), ext)

        return garantir_ext(f"doc_{doc_id}", ext)

    def baixar_url(self, url: str, out_path: Path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        last_status = None

        for attempt in range(1, 7):
            self._check_cancel()

            r = self.request_with_retry("GET", url, timeout=300, max_tries=1, stream=True)
            if r is None:
                last_status = "REDE"
            else:
                last_status = r.status_code
                if r.status_code == 200:
                    with open(out_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                f.write(chunk)
                    return True

            if last_status in RETRY_STATUS or last_status == "REDE":
                sleep_s = min(2 ** (attempt - 1), 30) + random.uniform(0, 0.8)
                self.log(f"AGUARD | Download HTTP {last_status} — tentativa {attempt}/6 — {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue

            break

        raise RuntimeError(f"Falha no download após retries. Último status: {last_status}")


# ---------------- Tooltip ----------------
class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, e=None):
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(
            tw,
            text=self.text,
            bg=TEXT_DARK,
            fg=WHITE,
            font=("Segoe UI", 8),
            padx=8,
            pady=4,
            relief="flat"
        )
        lbl.pack()

    def hide(self, e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------------- Log Parser ----------------
class LogLine:
    TAGS = {
        "OK":     ("✓", SUCCESS),
        "ERRO":   ("✕", DANGER),
        "AVISO":  ("!", WARNING),
        "INFO":   ("i", PRIMARY_2),
        "AGUARD": ("⏳", TEXT_SOFT),
        "REDE":   ("⚡", WARNING),
        "INICIO": ("▶", PRIMARY),
        "FIM":    ("■", PRIMARY),
    }

    @classmethod
    def parse(cls, msg: str):
        for key, (icon, fg) in cls.TAGS.items():
            if msg.startswith(key + " |") or msg.startswith(key + "|"):
                body = msg.split("|", 1)[1].strip()
                return icon, fg, body
        if "===" in msg:
            return "►", PRIMARY, msg.replace("===", "").strip()
        return "·", TEXT_SOFT, msg


# ---------------- Main App ----------------
class WebdoxDocumentDownloaderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Webdox Document Downloader")
        self.geometry("1120x820")
        self.minsize(920, 680)
        self.configure(bg=BG_MAIN)

        self.stop_event = threading.Event()
        self.worker_thread = None
        self._stats = {"total": 0, "done": 0, "erros": 0, "docs": 0}

        self._setup_fonts()
        self._build_ui()
        self._center_window()

    def _setup_fonts(self):
        self.f_title   = ("Segoe UI", 20, "bold")
        self.f_label   = ("Segoe UI", 10, "bold")
        self.f_body    = ("Segoe UI", 10)
        self.f_mono    = ("Consolas", 9)
        self.f_section = ("Segoe UI", 11, "bold")

    def _center_window(self):
        self.update_idletasks()
        w, h = 1120, 820
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _build_ui(self):
        outer = tk.Frame(self, bg=BG_MAIN)
        outer.pack(fill="both", expand=True)

        sidebar = tk.Frame(outer, bg=PRIMARY, width=270)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        main = tk.Frame(outer, bg=BG_MAIN)
        main.pack(side="left", fill="both", expand=True)
        self._build_main(main)

    def _build_sidebar(self, parent):
        top = tk.Frame(parent, bg=PRIMARY, padx=20, pady=24)
        top.pack(fill="x")

        tk.Label(
            top,
            text="Webdox Document Downloader",
            font=("Segoe UI", 16, "bold"),
            fg=WHITE,
            bg=PRIMARY,
            wraplength=220,
            justify="left"
        ).pack(anchor="w")

        tk.Label(
            top,
            text="Download de documentos via API Webdox",
            font=("Segoe UI", 9),
            fg="#C7D6F3",
            bg=PRIMARY
        ).pack(anchor="w", pady=(4, 0))

        tk.Frame(parent, bg="#355686", height=1).pack(fill="x", padx=20)

        status_frame = tk.Frame(parent, bg=PRIMARY, padx=20, pady=20)
        status_frame.pack(fill="x")

        tk.Label(
            status_frame,
            text="STATUS DA EXECUÇÃO",
            font=("Segoe UI", 8, "bold"),
            fg="#C7D6F3",
            bg=PRIMARY
        ).pack(anchor="w", pady=(0, 10))

        badge_row = tk.Frame(status_frame, bg=PRIMARY)
        badge_row.pack(fill="x", pady=(0, 14))
        self._state_dot = tk.Canvas(badge_row, width=10, height=10, bg=PRIMARY, highlightthickness=0)
        self._state_dot.pack(side="left", padx=(0, 6))
        self._state_lbl = tk.Label(
            badge_row,
            text="Aguardando",
            font=("Segoe UI", 10, "bold"),
            fg="#C7D6F3",
            bg=PRIMARY
        )
        self._state_lbl.pack(side="left")
        self._update_state_badge("idle")

        stats_grid = tk.Frame(status_frame, bg=PRIMARY)
        stats_grid.pack(fill="x")

        self._sv_total = tk.StringVar(value="0")
        self._sv_done  = tk.StringVar(value="0")
        self._sv_erros = tk.StringVar(value="0")
        self._sv_docs  = tk.StringVar(value="0")

        stats_data = [
            ("Workflows", self._sv_total, 0, 0),
            ("Concluídos", self._sv_done, 0, 1),
            ("Erros", self._sv_erros, 1, 0),
            ("Downloads", self._sv_docs, 1, 1),
        ]

        for label, var, row, col in stats_data:
            cell = tk.Frame(stats_grid, bg="#18365B", padx=10, pady=8)
            cell.grid(row=row, column=col, padx=3, pady=3, sticky="nsew")
            stats_grid.columnconfigure(col, weight=1)
            tk.Label(cell, textvariable=var, font=("Segoe UI", 18, "bold"), fg=WHITE, bg="#18365B").pack()
            tk.Label(cell, text=label, font=("Segoe UI", 7), fg="#C7D6F3", bg="#18365B").pack()

        tk.Frame(parent, bg="#355686", height=1).pack(fill="x", padx=20, pady=8)

        prog_frame = tk.Frame(parent, bg=PRIMARY, padx=20, pady=4)
        prog_frame.pack(fill="x")

        prog_header = tk.Frame(prog_frame, bg=PRIMARY)
        prog_header.pack(fill="x", pady=(0, 6))
        tk.Label(prog_header, text="PROGRESSO", font=("Segoe UI", 8, "bold"), fg="#C7D6F3", bg=PRIMARY).pack(side="left")
        self._pct_lbl = tk.Label(prog_header, text="0%", font=("Segoe UI", 8, "bold"), fg=WHITE, bg=PRIMARY)
        self._pct_lbl.pack(side="right")

        self._prog_canvas = tk.Canvas(prog_frame, height=6, bg="#18365B", highlightthickness=0, bd=0)
        self._prog_canvas.pack(fill="x")
        self._prog_value = 0.0
        self._prog_canvas.bind("<Configure>", self._redraw_progress)

        tk.Frame(parent, bg="#355686", height=1).pack(fill="x", padx=20, pady=12)

        time_frame = tk.Frame(parent, bg=PRIMARY, padx=20)
        time_frame.pack(fill="x")
        tk.Label(time_frame, text="TEMPO DECORRIDO", font=("Segoe UI", 8, "bold"), fg="#C7D6F3", bg=PRIMARY).pack(anchor="w", pady=(0, 4))
        self._timer_lbl = tk.Label(time_frame, text="00:00:00", font=("Consolas", 20, "bold"), fg=WHITE, bg=PRIMARY)
        self._timer_lbl.pack(anchor="w")

        self._start_time = None
        self._timer_running = False

        tk.Frame(parent, bg=PRIMARY).pack(fill="both", expand=True)

        footer = tk.Frame(parent, bg="#0F2747", padx=18, pady=12)
        footer.pack(fill="x", side="bottom")

        tk.Label(
            footer,
            text="Desenvolvido por Rodrigo Pinheiro",
            font=("Segoe UI", 9, "bold"),
            fg=WHITE,
            bg="#0F2747"
        ).pack(anchor="w")

        linkedin = tk.Label(
            footer,
            text="https://www.linkedin.com/in/rodrigo-s-pinheiro/",
            font=("Segoe UI", 8, "underline"),
            fg="#93C5FD",
            bg="#0F2747",
            cursor="hand2"
        )
        linkedin.pack(anchor="w", pady=(2, 0))
        linkedin.bind("<Button-1>", lambda e: webbrowser.open("https://www.linkedin.com/in/rodrigo-s-pinheiro/"))

    def _build_main(self, parent):
        header = tk.Frame(parent, bg=WHITE, padx=28, pady=18)
        header.pack(fill="x")
        tk.Frame(header, bg=BORDER, height=1).pack(fill="x", side="bottom")

        tk.Label(header, text="Configuração e Execução", font=self.f_title, fg=PRIMARY, bg=WHITE).pack(anchor="w")
        tk.Label(
            header,
            text="Conecte-se à Webdox, selecione um CSV com workflow_id, defina os termos e o sufixo final opcional, depois inicie o download.",
            font=self.f_body,
            fg=TEXT_SOFT,
            bg=WHITE
        ).pack(anchor="w", pady=(2, 0))

        canvas = tk.Canvas(parent, bg=BG_MAIN, highlightthickness=0)
        vscroll = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vscroll.set)

        vscroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=BG_MAIN)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def on_resize(e):
            canvas.itemconfig(win_id, width=e.width)
        canvas.bind("<Configure>", on_resize)

        def on_frame_resize(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", on_frame_resize)

        def _on_mousewheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        content = tk.Frame(inner, bg=BG_MAIN, padx=28, pady=20)
        content.pack(fill="both", expand=True)

        self._build_api_card(content)
        self._build_io_card(content)
        self._build_search_card(content)
        self._build_actions_bar(content)
        self._build_log_card(content)

    def _card(self, parent, title: str, icon: str = "") -> tk.Frame:
        wrapper = tk.Frame(parent, bg=BG_CARD)
        wrapper.pack(fill="x", pady=(0, 16))

        tk.Frame(wrapper, bg=ACCENT, height=3).pack(fill="x")
        tk.Frame(wrapper, bg=SHADOW_COLOR, height=1).pack(fill="x")

        hdr = tk.Frame(wrapper, bg=BG_CARD, padx=20, pady=12)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg="#EEF3FB", height=1).pack(fill="x", side="bottom")

        title_txt = f"{icon}  {title}" if icon else title
        tk.Label(hdr, text=title_txt, font=self.f_section, fg=PRIMARY, bg=BG_CARD).pack(anchor="w")

        body = tk.Frame(wrapper, bg=BG_CARD, padx=20, pady=16)
        body.pack(fill="x")
        return body

    def _styled_entry(self, parent, textvariable=None, show="", placeholder=""):
        frame = tk.Frame(parent, bg=BORDER, padx=1, pady=1)
        inner_frame = tk.Frame(frame, bg=WHITE)
        inner_frame.pack(fill="both", expand=True)

        entry = tk.Entry(
            inner_frame,
            textvariable=textvariable,
            show=show,
            font=self.f_body,
            fg=TEXT_MAIN,
            bg=WHITE,
            relief="flat",
            bd=0,
            highlightthickness=0,
            insertbackground=PRIMARY_2
        )
        entry.pack(fill="both", expand=True, padx=8, pady=6)

        if placeholder:
            entry.insert(0, placeholder)
            entry.config(fg="#9CA3AF")
            entry._has_ph = True

            def on_focus_in(e):
                if entry._has_ph:
                    entry.delete(0, "end")
                    entry.config(fg=TEXT_MAIN, show=show)
                    entry._has_ph = False

            def on_focus_out(e):
                if not entry.get():
                    entry.insert(0, placeholder)
                    entry.config(fg="#9CA3AF", show="")
                    entry._has_ph = True

            entry.bind("<FocusIn>", on_focus_in)
            entry.bind("<FocusOut>", on_focus_out)

        entry.bind("<FocusIn>", lambda e: frame.config(bg=PRIMARY_2))
        entry.bind("<FocusOut>", lambda e: frame.config(bg=BORDER))

        return frame, entry

    def _btn_primary(self, parent, text, command, icon=""):
        txt = f"{icon}  {text}" if icon else text
        btn = tk.Button(
            parent,
            text=txt,
            font=("Segoe UI", 10, "bold"),
            bg=PRIMARY_2,
            fg=WHITE,
            relief="flat",
            bd=0,
            padx=18,
            pady=10,
            cursor="hand2",
            activebackground=PRIMARY,
            activeforeground=WHITE,
            command=command
        )
        btn.bind("<Enter>", lambda e: btn.config(bg=PRIMARY))
        btn.bind("<Leave>", lambda e: btn.config(bg=PRIMARY_2))
        return btn

    def _btn_danger(self, parent, text, command, icon=""):
        txt = f"{icon}  {text}" if icon else text
        btn = tk.Button(
            parent,
            text=txt,
            font=("Segoe UI", 10, "bold"),
            bg=DANGER,
            fg=WHITE,
            relief="flat",
            bd=0,
            padx=18,
            pady=10,
            cursor="hand2",
            activebackground="#B91C1C",
            activeforeground=WHITE,
            command=command
        )
        btn.bind("<Enter>", lambda e: btn.config(bg="#B91C1C"))
        btn.bind("<Leave>", lambda e: btn.config(bg=DANGER))
        return btn

    def _btn_secondary(self, parent, text, command):
        btn = tk.Button(
            parent,
            text=text,
            font=self.f_body,
            bg="#F3F6FB",
            fg=TEXT_MAIN,
            relief="flat",
            bd=0,
            padx=14,
            pady=9,
            cursor="hand2",
            activebackground="#E5ECF7",
            activeforeground=TEXT_MAIN,
            command=command
        )
        btn.bind("<Enter>", lambda e: btn.config(bg="#E5ECF7"))
        btn.bind("<Leave>", lambda e: btn.config(bg="#F3F6FB"))
        return btn

    def _form_field(self, parent, label_text, var, show="", placeholder=""):
        tk.Label(parent, text=label_text, font=self.f_label, fg=TEXT_MAIN, bg=BG_CARD, anchor="w").pack(fill="x", pady=(0, 4))
        border, entry = self._styled_entry(parent, textvariable=var, show=show, placeholder=placeholder)
        border.pack(fill="x", pady=(0, 12))
        return entry

    def _collect_active_search_terms(self) -> list[str]:
        termos = []
        for item in getattr(self, "_search_term_rows", []):
            if item["enabled_var"].get():
                valor = item["text_var"].get().strip()
                if valor:
                    termos.append(normalize_key(valor))
        return termos

    def _remove_search_term_row(self, row_frame):
        if not hasattr(self, "_search_term_rows"):
            return

        nova_lista = []
        for item in self._search_term_rows:
            if item["frame"] == row_frame:
                item["frame"].destroy()
            else:
                nova_lista.append(item)

        self._search_term_rows = nova_lista

        if not self._search_term_rows:
            self._add_search_term_row()

    def _add_search_term_row(self, value: str = "", enabled: bool = True):
        row = tk.Frame(self.search_terms_container, bg=BG_CARD)
        row.pack(fill="x", pady=(0, 8))

        enabled_var = tk.BooleanVar(value=enabled)
        text_var = tk.StringVar(value=value)

        cb = tk.Checkbutton(
            row,
            variable=enabled_var,
            bg=BG_CARD,
            activebackground=BG_CARD,
            cursor="hand2",
            selectcolor=ACCENT,
            relief="flat"
        )
        cb.pack(side="left", padx=(0, 8))

        entry_wrap, entry = self._styled_entry(
            row,
            textvariable=text_var,
            placeholder="Ex: COMPROVANTE_FISCAL"
        )
        entry_wrap.pack(side="left", fill="x", expand=True)

        btn_remove = tk.Button(
            row,
            text="✕",
            font=("Segoe UI", 10, "bold"),
            bg="#FDECEC",
            fg="#C0392B",
            relief="flat",
            bd=0,
            width=3,
            padx=0,
            pady=6,
            cursor="hand2",
            activebackground="#FADBD8",
            activeforeground="#A93226",
            command=lambda rf=row: self._remove_search_term_row(rf)
        )
        btn_remove.pack(side="left", padx=(8, 0))

        self._search_term_rows.append({
            "frame": row,
            "enabled_var": enabled_var,
            "text_var": text_var,
            "entry": entry
        })

    def _build_api_card(self, parent):
        body = self._card(parent, "Conexão com a Webdox", "🔐")

        self.var_base_url = tk.StringVar(value=DEFAULT_BASE_URL)
        self.var_user = tk.StringVar()
        self.var_pass = tk.StringVar()
        self.var_tenant = tk.StringVar()

        self._form_field(body, "Base URL da API", self.var_base_url)
        self._form_field(body, "Usuário / E-mail", self.var_user)
        self._form_field(body, "Senha", self.var_pass, show="•")
        self._form_field(body, "Ambiente / Customer (opcional)", self.var_tenant)

        hint = tk.Frame(body, bg=INFO_BG, padx=10, pady=8)
        hint.pack(fill="x", pady=(4, 0))
        tk.Label(
            hint,
            text="ℹ  Informe suas próprias credenciais da Webdox. O aplicativo não salva usuário e senha localmente.",
            font=("Segoe UI", 8),
            fg=PRIMARY_2,
            bg=INFO_BG
        ).pack(anchor="w")

    def _build_io_card(self, parent):
        body = self._card(parent, "Entrada e Saída", "📁")

        row1 = tk.Frame(body, bg=BG_CARD)
        row1.pack(fill="x", pady=(0, 12))
        row1.columnconfigure(1, weight=1)

        tk.Label(row1, text="Arquivo CSV", font=self.f_label, fg=TEXT_MAIN, bg=BG_CARD, width=14, anchor="w").grid(row=0, column=0, sticky="w")

        self.var_csv = tk.StringVar()
        csv_frame = tk.Frame(row1, bg=BG_CARD)
        csv_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        csv_frame.columnconfigure(0, weight=1)

        entry_wrap, self._entry_csv = self._styled_entry(csv_frame, textvariable=self.var_csv, placeholder="Selecione um arquivo CSV...")
        entry_wrap.grid(row=0, column=0, sticky="ew")
        self._btn_secondary(csv_frame, "Procurar...", self.browse_csv).grid(row=0, column=1, padx=(8, 0))

        row2 = tk.Frame(body, bg=BG_CARD)
        row2.pack(fill="x")
        row2.columnconfigure(1, weight=1)

        tk.Label(row2, text="Pasta de saída", font=self.f_label, fg=TEXT_MAIN, bg=BG_CARD, width=14, anchor="w").grid(row=0, column=0, sticky="w")

        self.var_out = tk.StringVar(value=str(Path.cwd() / "downloads_webdox"))
        out_frame = tk.Frame(row2, bg=BG_CARD)
        out_frame.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        out_frame.columnconfigure(0, weight=1)

        entry_wrap2, self._entry_out = self._styled_entry(out_frame, textvariable=self.var_out)
        entry_wrap2.grid(row=0, column=0, sticky="ew")
        self._btn_secondary(out_frame, "Selecionar...", self.browse_out).grid(row=0, column=1, padx=(8, 0))

    def _build_search_card(self, parent):
        body = self._card(parent, "Busca de Documentos", "🔎")

        self._search_term_rows = []
        self.var_suffix = tk.StringVar()

        header_row = tk.Frame(body, bg=BG_CARD)
        header_row.pack(fill="x", pady=(0, 8))

        title_wrap = tk.Frame(header_row, bg=BG_CARD)
        title_wrap.pack(side="left", fill="x", expand=True)

        lbl = tk.Label(
            title_wrap,
            text="Termos de busca",
            font=self.f_label,
            fg=TEXT_MAIN,
            bg=BG_CARD,
            anchor="w"
        )
        lbl.pack(side="left")

        tip = tk.Label(
            title_wrap,
            text="?",
            font=("Segoe UI", 8),
            fg=PRIMARY_2,
            bg=BG_CARD
        )
        tip.pack(side="left", padx=(6, 0))
        Tooltip(tip, "Marque os termos que deseja considerar na busca. Desmarque para ignorar temporariamente.")

        btn_add = tk.Button(
            header_row,
            text="+  Adicionar termo",
            font=("Segoe UI", 9),
            bg="#EEF3FB",
            fg=PRIMARY_2,
            relief="flat",
            bd=0,
            padx=12,
            pady=8,
            cursor="hand2",
            activebackground="#E2EAF8",
            activeforeground=PRIMARY,
            command=lambda: self._add_search_term_row()
        )
        btn_add.pack(side="right")

        self.search_terms_container = tk.Frame(body, bg=BG_CARD)
        self.search_terms_container.pack(fill="x")

        self._add_search_term_row()

        hint = tk.Frame(body, bg=INFO_BG, padx=10, pady=8)
        hint.pack(fill="x", pady=(4, 10))
        tk.Label(
            hint,
            text="ℹ  Você pode adicionar vários termos. O documento será baixado se corresponder a pelo menos um termo ativo. Se todos estiverem vazios, todos os documentos serão considerados.",
            font=("Segoe UI", 8),
            fg=PRIMARY_2,
            bg=INFO_BG,
            wraplength=760,
            justify="left"
        ).pack(anchor="w")

        suffix_title_row = tk.Frame(body, bg=BG_CARD)
        suffix_title_row.pack(fill="x", pady=(4, 6))

        suffix_label = tk.Label(
            suffix_title_row,
            text="Definir sufixo ao buscar documentos",
            font=self.f_label,
            fg=TEXT_MAIN,
            bg=BG_CARD,
            anchor="w"
        )
        suffix_label.pack(side="left")

        suffix_tip = tk.Label(
            suffix_title_row,
            text="?",
            font=("Segoe UI", 8),
            fg=PRIMARY_2,
            bg=BG_CARD
        )
        suffix_tip.pack(side="left", padx=(6, 0))
        Tooltip(
            suffix_tip,
            "Ao adicionar o termo final, a buscar dos termos anteriores se limita aos documentos que apresentarem o sufixo definido. Exemplo: -assinado.pdf"
        )

        suffix_row = tk.Frame(body, bg=BG_CARD)
        suffix_row.pack(fill="x", pady=(0, 12))

        suffix_wrap, self._entry_suffix = self._styled_entry(
            suffix_row,
            textvariable=self.var_suffix,
            placeholder='Ex: -assinado.pdf (deixe em branco para uma busca ampla dos termos anteriores)'
        )
        suffix_wrap.pack(fill="x", expand=True)

        self._opt_merge = tk.BooleanVar(value=True)

        row = tk.Frame(body, bg=BG_CARD)
        row.pack(fill="x", pady=(2, 0))

        cb = tk.Checkbutton(
            row,
            variable=self._opt_merge,
            bg=BG_CARD,
            activebackground=BG_CARD,
            cursor="hand2",
            selectcolor=ACCENT,
            relief="flat"
        )
        cb.pack(side="left")

        lbl_merge = tk.Label(
            row,
            text="Mesclar PDFs baixados por workflow",
            font=self.f_body,
            fg=TEXT_MAIN,
            bg=BG_CARD,
            cursor="hand2"
        )
        lbl_merge.pack(side="left", padx=(4, 0))
        lbl_merge.bind("<Button-1>", lambda e: self._opt_merge.set(not self._opt_merge.get()))

    def _build_actions_bar(self, parent):
        bar = tk.Frame(parent, bg=BG_MAIN, pady=4)
        bar.pack(fill="x", pady=(0, 16))

        left_btns = tk.Frame(bar, bg=BG_MAIN)
        left_btns.pack(side="left")

        self.btn_start = self._btn_primary(left_btns, "Iniciar Download", self.start, "▶")
        self.btn_start.pack(side="left")

        self.btn_cancel = self._btn_danger(left_btns, "Cancelar", self.cancel, "⛔")
        self.btn_cancel.pack(side="left", padx=(10, 0))
        self.btn_cancel.config(state="disabled", bg="#F0A7A7")

        self._btn_secondary(bar, "Limpar log", self._clear_log).pack(side="right")

    def _build_log_card(self, parent):
        wrapper = tk.Frame(parent, bg=BG_CARD)
        wrapper.pack(fill="both", expand=True)

        tk.Frame(wrapper, bg=PRIMARY, height=3).pack(fill="x")
        tk.Frame(wrapper, bg=SHADOW_COLOR, height=1).pack(fill="x")

        hdr = tk.Frame(wrapper, bg=BG_CARD, padx=20, pady=10)
        hdr.pack(fill="x")
        tk.Frame(hdr, bg="#EEF3FB", height=1).pack(fill="x", side="bottom")

        tk.Label(hdr, text="🧾  Log de Execução", font=self.f_section, fg=PRIMARY, bg=BG_CARD).pack(side="left")

        self._log_count_lbl = tk.Label(hdr, text="0 entradas", font=("Segoe UI", 8), fg=TEXT_SOFT, bg=BG_CARD)
        self._log_count_lbl.pack(side="right")

        log_body = tk.Frame(wrapper, bg=TEXT_DARK)
        log_body.pack(fill="both", expand=True)

        self.txt = tk.Text(
            log_body,
            wrap="word",
            height=16,
            font=self.f_mono,
            bg="#0B1523",
            fg="#CBD5E1",
            insertbackground=WHITE,
            selectbackground=PRIMARY_2,
            selectforeground=WHITE,
            relief="flat",
            bd=0,
            padx=16,
            pady=12,
            spacing1=2,
            spacing2=1,
            spacing3=3,
        )
        self.txt.pack(side="left", fill="both", expand=True)

        scroll = tk.Scrollbar(log_body, command=self.txt.yview)
        scroll.pack(side="right", fill="y")
        self.txt.config(yscrollcommand=scroll.set, state="disabled")

        self.txt.tag_configure("OK", foreground=SUCCESS)
        self.txt.tag_configure("ERRO", foreground=DANGER)
        self.txt.tag_configure("AVISO", foreground=WARNING)
        self.txt.tag_configure("INFO", foreground="#93C5FD")
        self.txt.tag_configure("AGUARD", foreground="#94A3B8")
        self.txt.tag_configure("REDE", foreground=WARNING)
        self.txt.tag_configure("INICIO", foreground="#60A5FA", font=("Consolas", 9, "bold"))
        self.txt.tag_configure("FIM", foreground="#60A5FA", font=("Consolas", 9, "bold"))
        self.txt.tag_configure("TS", foreground="#475569")
        self.txt.tag_configure("DEFAULT", foreground="#94A3B8")
        self.txt.tag_configure("SECTION", foreground="#60A5FA", font=("Consolas", 9, "bold"))

        self._log_count = 0

    def _update_state_badge(self, state: str):
        colors = {
            "idle":      ("#94A3B8", "Aguardando"),
            "running":   (ACCENT, "Executando"),
            "success":   (SUCCESS, "Concluído"),
            "error":     (DANGER, "Erro"),
            "cancelled": (WARNING, "Cancelado"),
        }
        color, label = colors.get(state, colors["idle"])
        self._state_dot.delete("all")
        self._state_dot.create_oval(1, 1, 9, 9, fill=color, outline="")
        self._state_lbl.config(text=label, fg=color if state != "idle" else "#C7D6F3")

    def _redraw_progress(self, e=None):
        w = self._prog_canvas.winfo_width()
        h = self._prog_canvas.winfo_height()
        self._prog_canvas.delete("all")
        self._prog_canvas.create_rectangle(0, 0, w, h, fill="#18365B", outline="")
        fill_w = int(w * self._prog_value)
        if fill_w > 0:
            self._prog_canvas.create_rectangle(0, 0, fill_w, h, fill=ACCENT, outline="")

    def _set_progress(self, value: float):
        self._prog_value = max(0.0, min(1.0, value))
        pct = int(self._prog_value * 100)
        self._pct_lbl.config(text=f"{pct}%")
        self._redraw_progress()

    def log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")

        def _append():
            self.txt.configure(state="normal")

            icon, fg, body = LogLine.parse(msg)
            tag = "DEFAULT"
            for key in LogLine.TAGS:
                if msg.startswith(key + " |") or msg.startswith(key + "|"):
                    tag = key
                    break
            if "===" in msg:
                tag = "SECTION"

            self.txt.insert("end", f"[{ts}] ", "TS")
            self.txt.insert("end", f"{icon} ", tag)
            self.txt.insert("end", body + "\n", tag)

            self.txt.see("end")
            self.txt.configure(state="disabled")

            self._log_count += 1
            self._log_count_lbl.config(text=f"{self._log_count} entradas")

        self.after(0, _append)

    def _clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        self._log_count = 0
        self._log_count_lbl.config(text="0 entradas")

    def browse_csv(self):
        path = filedialog.askopenfilename(
            title="Selecione o CSV",
            filetypes=[("CSV", "*.csv"), ("Todos os arquivos", "*.*")]
        )
        if path:
            self.var_csv.set(path)

    def browse_out(self):
        path = filedialog.askdirectory(title="Selecione a pasta de saída")
        if path:
            self.var_out.set(path)

    def set_running(self, running: bool):
        def _set():
            if running:
                self.btn_start.config(state="disabled", bg="#86AEEA")
                self.btn_cancel.config(state="normal", bg=DANGER)
                self._update_state_badge("running")
                self._start_timer()
            else:
                self.btn_start.config(state="normal", bg=PRIMARY_2)
                self.btn_cancel.config(state="disabled", bg="#F0A7A7")
                self._stop_timer()
        self.after(0, _set)

    def _start_timer(self):
        self._start_time = time.time()
        self._timer_running = True
        self._tick_timer()

    def _stop_timer(self):
        self._timer_running = False

    def _tick_timer(self):
        if not self._timer_running:
            return
        elapsed = int(time.time() - self._start_time)
        h = elapsed // 3600
        m = (elapsed % 3600) // 60
        s = elapsed % 60
        self._timer_lbl.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.after(1000, self._tick_timer)

    def start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return

        base_url = (self.var_base_url.get() or "").strip()
        if not base_url:
            base_url = DEFAULT_BASE_URL

        user = self.var_user.get().strip()
        pw = self.var_pass.get()
        ambiente = self.var_tenant.get().strip()
        csv_path = self.var_csv.get().strip()
        out_dir = self.var_out.get().strip()

        if not user or not pw:
            messagebox.showerror("Campos obrigatórios", "Informe usuário e senha.")
            return
        if not csv_path or not Path(csv_path).exists():
            messagebox.showerror("Arquivo inválido", "Selecione um CSV válido com a coluna 'workflow_id'.")
            return

        self.stop_event.clear()
        self._stats = {"total": 0, "done": 0, "erros": 0, "docs": 0}
        self._sv_total.set("0")
        self._sv_done.set("0")
        self._sv_erros.set("0")
        self._sv_docs.set("0")
        self._set_progress(0.0)
        self.set_running(True)

        self.worker_thread = threading.Thread(
            target=self.run_job,
            args=(base_url, user, pw, ambiente, csv_path, out_dir),
            daemon=True
        )
        self.worker_thread.start()

    def cancel(self):
        self.stop_event.set()
        self.log("FIM | Cancelamento solicitado... aguardando a etapa atual finalizar.")
        self.after(0, lambda: self._update_state_badge("cancelled"))

    def run_job(self, base_url, user, pw, ambiente, csv_path, out_dir):
        try:
            self.log("INICIO | Iniciando processo de download")
            self.log("INFO | Carregando CSV...")

            workflow_ids = read_workflow_ids(csv_path)
            if not workflow_ids:
                raise RuntimeError("O CSV não possui workflow_ids válidos.")

            total = len(workflow_ids)
            self._stats["total"] = total
            self.after(0, lambda: self._sv_total.set(str(total)))
            self.log(f"INFO | {total} workflow(s) encontrado(s) no CSV")

            client = WebdoxClient(base_url, user, pw, ambiente, self.log, self.stop_event)
            self.log("INFO | Autenticando na Webdox...")
            client.login()

            base_out = Path(out_dir)
            base_out.mkdir(parents=True, exist_ok=True)
            report_rows = []

            do_merge = self._opt_merge.get()
            termos_incluir = self._collect_active_search_terms()
            suffix = (self.var_suffix.get() or "").strip()

            if suffix:
                self.log(f"INFO | Sufixo definido para filtro final: {suffix}")

            for idx, workflow_id in enumerate(workflow_ids, start=1):
                if self.stop_event.is_set():
                    raise Cancelled("Operação cancelada pelo usuário.")

                self.log(f"=== [{idx}/{total}] Workflow {workflow_id} ===")
                self.after(0, lambda i=idx: self._set_progress(i / total))

                docs_raw, err = client.listar_docs_workflow(workflow_id)
                if err:
                    workflow_info = client.get_workflow_info(workflow_id) or {}
                    workflow_name = workflow_info.get("decision_name") or workflow_info.get("name") or ""
                    self.log(f"AVISO | Falha ao listar documentos: {err[0]}")

                    report_rows.append({
                        "workflow_id": workflow_id,
                        "workflow_name": workflow_name,
                        "docs_encontrados": 0,
                        "docs_baixados": 0
                    })

                    self._stats["erros"] += 1
                    self.after(0, lambda: self._sv_erros.set(str(self._stats["erros"])))
                    continue

                docs = client.normalizar_docs(docs_raw)

                candidatos = []
                for d in docs:
                    nome = client.escolher_nome(d["doc_id"], d.get("nome_hint"))
                    candidatos.append({**d, "nome": nome})

                docs_alvo = [d for d in candidatos if eh_documento_alvo(d["nome"], termos_incluir, suffix)]
                self.log(f"INFO | {len(docs_alvo)} documento(s) correspondente(s) encontrado(s)")

                workflow_info = client.get_workflow_info(workflow_id) or {}
                workflow_name = workflow_info.get("decision_name") or workflow_info.get("name") or ""

                pasta_workflow = base_out / f"workflow_{workflow_id}"
                pasta_workflow.mkdir(parents=True, exist_ok=True)

                baixados_paths = []
                for j, d in enumerate(docs_alvo, start=1):
                    if self.stop_event.is_set():
                        raise Cancelled("Operação cancelada.")

                    nome_final = safe_filename(d["nome"])
                    out_path = pasta_workflow / nome_final
                    self.log(f"INFO | [{j}/{len(docs_alvo)}] Baixando: {nome_final}")

                    try:
                        client.baixar_url(d["download_url"], out_path)
                        baixados_paths.append(out_path)
                        self._stats["docs"] += 1
                        self.after(0, lambda: self._sv_docs.set(str(self._stats["docs"])))
                        self.log(f"OK | Download concluído: {nome_final}")
                    except Exception as e:
                        self.log(f"ERRO | Falha no download: {e}")

                if do_merge:
                    merged_pdf = pasta_workflow / f"workflow_{workflow_id}__MERGED.pdf"
                    if merge_pdfs(baixados_paths, merged_pdf):
                        self.log(f"OK | PDF mesclado gerado: {merged_pdf.name}")
                    else:
                        self.log("AVISO | Nenhum PDF para mesclar neste workflow")

                report_rows.append({
                    "workflow_id": workflow_id,
                    "workflow_name": workflow_name,
                    "docs_encontrados": len(docs_alvo),
                    "docs_baixados": len(baixados_paths)
                })

                self._stats["done"] += 1
                self.after(0, lambda: self._sv_done.set(str(self._stats["done"])))

            report_path = base_out / "RELATORIO_DOWNLOADS.xlsx"
            write_report_xlsx(report_path, report_rows)

            self.log(f"OK | Relatório salvo em: {report_path}")
            self.log("FIM | Processo concluído com sucesso!")

            self.after(0, lambda: self._update_state_badge("success"))
            self.after(0, lambda: self._set_progress(1.0))
            self.after(0, lambda: messagebox.showinfo(
                "Concluído",
                f"Download finalizado!\n\n"
                f"• Workflows processados: {self._stats['done']}/{self._stats['total']}\n"
                f"• Documentos baixados: {self._stats['docs']}\n"
                f"• Erros: {self._stats['erros']}\n\n"
                f"Relatório: {report_path}"
            ))

        except Cancelled as e:
            self.log(f"FIM | {e}")
            self.after(0, lambda: self._update_state_badge("cancelled"))
        except Exception as e:
            self.log(f"ERRO | {e}")
            self.after(0, lambda: self._update_state_badge("error"))
            self.after(0, lambda: messagebox.showerror("Erro", str(e)))
        finally:
            self.set_running(False)


def main():
    app = WebdoxDocumentDownloaderApp()
    app.mainloop()


if __name__ == "__main__":
    main()