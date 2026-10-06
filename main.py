"""
J.A.R.V.I.S — Android (Kivy)
Groq STT + Llama 3.3 70b + ElevenLabs TTS
"""
import os, json, threading, datetime, traceback
from pathlib import Path

# ── Kivy ayarları (import öncesi) ─────────────────────
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.widget import Widget
from kivy.graphics import Color, RoundedRectangle, Rectangle
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.utils import platform
from kivy.properties import StringProperty, BooleanProperty

# Android izinleri
if platform == "android":
    from android.permissions import request_permissions, Permission
    request_permissions([
        Permission.RECORD_AUDIO,
        Permission.INTERNET,
        Permission.WRITE_EXTERNAL_STORAGE,
        Permission.READ_EXTERNAL_STORAGE,
    ])

# ── Renkler ────────────────────────────────────────────
TEAL   = (0.08, 1.0, 0.93, 1)
TEAL2  = (0.05, 0.45, 0.45, 1)
BG     = (0.02, 0.05, 0.05, 1)
BG2    = (0.04, 0.10, 0.10, 1)
GOLD   = (1.0, 0.76, 0.03, 1)
RED    = (1.0, 0.20, 0.20, 1)
MID    = (0.31, 0.48, 0.47, 1)
WHITE  = (1, 1, 1, 1)

# ── Veri yolları ───────────────────────────────────────
if platform == "android":
    from android.storage import app_storage_path
    BASE = Path(app_storage_path())
else:
    BASE = Path(__file__).parent

VERI_DOSYASI   = BASE / "jarvis_veri.json"
HAFIZA_DOSYASI = BASE / "jarvis_hafiza.json"
TAKVIM_DOSYASI = BASE / "jarvis_takvim.json"
HATIRLAT_FILE  = BASE / "jarvis_hatirlat.json"
VIDEO_TAKIP    = BASE / "jarvis_video.json"

# ── Config ─────────────────────────────────────────────
VARSAYILAN = {
    "groq_api_key":       "",
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id":"",
}

def konfig_yukle():
    try:
        if VERI_DOSYASI.exists():
            d = json.loads(VERI_DOSYASI.read_text(encoding="utf-8"))
            cfg = dict(VARSAYILAN); cfg.update(d); return cfg
    except Exception: pass
    return dict(VARSAYILAN)

def konfig_kaydet(guncellemeler):
    cfg = konfig_yukle(); cfg.update(guncellemeler)
    VERI_DOSYASI.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg

def konfig_al(anahtar, varsayilan=""):
    return konfig_yukle().get(anahtar, varsayilan)

# ── Hafıza ─────────────────────────────────────────────
def hafiza_yukle():
    try:
        if HAFIZA_DOSYASI.exists():
            return json.loads(HAFIZA_DOSYASI.read_text(encoding="utf-8"))
    except Exception: pass
    return {}

def hafiza_guncelle(veri):
    mevcut = hafiza_yukle()
    def _birlestir(a, b):
        for k, v in b.items():
            if isinstance(v, dict) and isinstance(a.get(k), dict):
                _birlestir(a[k], v)
            else:
                a[k] = v
    _birlestir(mevcut, veri)
    HAFIZA_DOSYASI.write_text(json.dumps(mevcut, indent=2, ensure_ascii=False), encoding="utf-8")

def hafiza_formatla(hafiza):
    if not hafiza: return ""
    satirlar = ["[KULLANICI HAFIZASI]"]
    for kategori, veriler in hafiza.items():
        if isinstance(veriler, dict):
            for anahtar, entry in veriler.items():
                deger = entry.get("value", entry) if isinstance(entry, dict) else entry
                satirlar.append(f"{kategori}/{anahtar}: {deger}")
    return "\n".join(satirlar)

# ── Groq AI ────────────────────────────────────────────
SISTEM_PROMPT = """Sen JARVIS'sin — Android telefonunda çalışan kişisel AI asistanı.
Türkçe konuş. Kısa ve net cevaplar ver.
Kullanıcının adı Berat Yiğit Değirmenci.
Araçları kullanarak görevleri tamamla, asla uydurma."""

GROQ_ARACLAR = [
    {"type":"function","function":{"name":"hava_durumu","description":"Hava durumunu getirir.","parameters":{"type":"object","properties":{"konum":{"type":"string"}}}}},
    {"type":"function","function":{"name":"takvim_oku","description":"Takvim etkinliklerini okur.","parameters":{"type":"object","properties":{"sorgu":{"type":"string","description":"bugun|yarin|hafta"}},"required":["sorgu"]}}},
    {"type":"function","function":{"name":"takvim_ekle","description":"Takvime etkinlik ekler.","parameters":{"type":"object","properties":{"baslik":{"type":"string"},"baslangic":{"type":"string"},"notlar":{"type":"string"}},"required":["baslik","baslangic"]}}},
    {"type":"function","function":{"name":"hatirlat_ekle","description":"Hatırlatıcı ekler.","parameters":{"type":"object","properties":{"baslik":{"type":"string"},"tarih":{"type":"string"},"notlar":{"type":"string"}},"required":["baslik"]}}},
    {"type":"function","function":{"name":"hatirlat_oku","description":"Hatırlatıcıları okur.","parameters":{"type":"object","properties":{"sorgu":{"type":"string"}}}}},
    {"type":"function","function":{"name":"hafiza_kaydet","description":"Önemli bilgiyi hafızaya kaydeder.","parameters":{"type":"object","properties":{"kategori":{"type":"string"},"anahtar":{"type":"string"},"deger":{"type":"string"}},"required":["kategori","anahtar","deger"]}}},
    {"type":"function","function":{"name":"uygulama_ac","description":"Telefonda uygulama açar.","parameters":{"type":"object","properties":{"uygulama":{"type":"string"}},"required":["uygulama"]}}},
    {"type":"function","function":{"name":"web_ara","description":"Tarayıcıda arama yapar.","parameters":{"type":"object","properties":{"sorgu":{"type":"string"}},"required":["sorgu"]}}},
    {"type":"function","function":{"name":"ders_durumu","description":"Ders programını sorgular.","parameters":{"type":"object","properties":{"sorgu":{"type":"string"}}}}},
]

def araci_calistir(isim, argumanlar):
    import requests as _req
    try:
        if isim == "hava_durumu":
            konum = argumanlar.get("konum", "Istanbul")
            r = _req.get(f"https://wttr.in/{konum}?format=3&lang=tr", timeout=8)
            return r.text.strip() if r.ok else "Hava durumu alınamadı."

        elif isim == "takvim_oku":
            if not TAKVIM_DOSYASI.exists(): return "Takvimde etkinlik yok."
            etkinlikler = json.loads(TAKVIM_DOSYASI.read_text(encoding="utf-8"))
            simdi = datetime.datetime.now()
            sorgu = argumanlar.get("sorgu", "bugun")
            if sorgu == "bugun":
                hedef = simdi.date()
                filtre = [e for e in etkinlikler if e.get("baslangic","")[:10] == str(hedef)]
            elif sorgu == "yarin":
                hedef = (simdi + datetime.timedelta(days=1)).date()
                filtre = [e for e in etkinlikler if e.get("baslangic","")[:10] == str(hedef)]
            else:
                filtre = etkinlikler[:8]
            if not filtre: return f"{sorgu} için etkinlik yok."
            return "\n".join(f"• {e['baslik']} ({e.get('baslangic','?')[:16]})" for e in filtre)

        elif isim == "takvim_ekle":
            import uuid
            etkinlikler = json.loads(TAKVIM_DOSYASI.read_text(encoding="utf-8")) if TAKVIM_DOSYASI.exists() else []
            etkinlikler.append({
                "id": str(uuid.uuid4())[:8],
                "baslik": argumanlar.get("baslik",""),
                "baslangic": argumanlar.get("baslangic",""),
                "notlar": argumanlar.get("notlar",""),
                "olusturuldu": datetime.datetime.now().isoformat()
            })
            TAKVIM_DOSYASI.write_text(json.dumps(etkinlikler, indent=2, ensure_ascii=False), encoding="utf-8")
            return f"✅ Eklendi: {argumanlar.get('baslik')}"

        elif isim == "hatirlat_ekle":
            import uuid
            kayitlar = json.loads(HATIRLAT_FILE.read_text(encoding="utf-8")) if HATIRLAT_FILE.exists() else []
            kayitlar.append({
                "id": str(uuid.uuid4())[:8],
                "baslik": argumanlar.get("baslik",""),
                "tarih": argumanlar.get("tarih",""),
                "notlar": argumanlar.get("notlar",""),
                "tamamlandi": False
            })
            HATIRLAT_FILE.write_text(json.dumps(kayitlar, indent=2, ensure_ascii=False), encoding="utf-8")
            return f"✅ Hatırlatıcı eklendi: {argumanlar.get('baslik')}"

        elif isim == "hatirlat_oku":
            if not HATIRLAT_FILE.exists(): return "Hatırlatıcı yok."
            kayitlar = [r for r in json.loads(HATIRLAT_FILE.read_text(encoding="utf-8")) if not r.get("tamamlandi")]
            if not kayitlar: return "Aktif hatırlatıcı yok."
            return "\n".join(f"• {r['baslik']}" + (f" ({r['tarih']})" if r.get('tarih') else "") for r in kayitlar[:8])

        elif isim == "hafiza_kaydet":
            hafiza_guncelle({argumanlar.get("kategori","not"): {argumanlar.get("anahtar","bilgi"): {"value": argumanlar.get("deger","")}}})
            return "Hafızaya kaydedildi."

        elif isim == "uygulama_ac":
            uygulama = argumanlar.get("uygulama","").lower()
            if platform == "android":
                from jnius import autoclass
                Intent   = autoclass("android.content.Intent")
                Uri      = autoclass("android.net.Uri")
                PActivity= autoclass("org.kivy.android.PythonActivity").mActivity
                paketler = {
                    "whatsapp":  "com.whatsapp",
                    "spotify":   "com.spotify.music",
                    "youtube":   "com.google.android.youtube",
                    "instagram": "com.instagram.android",
                    "telegram":  "org.telegram.messenger",
                    "chrome":    "com.android.chrome",
                }
                paket = paketler.get(uygulama)
                if paket:
                    pm = PActivity.getPackageManager()
                    intent = pm.getLaunchIntentForPackage(paket)
                    if intent: PActivity.startActivity(intent); return f"{uygulama} açıldı."
            return f"{uygulama} açılmaya çalışıldı."

        elif isim == "web_ara":
            sorgu = argumanlar.get("sorgu","")
            import webbrowser
            webbrowser.open(f"https://www.google.com/search?q={sorgu}")
            return f"'{sorgu}' araması açıldı."

        elif isim == "ders_durumu":
            simdi = datetime.datetime.now()
            gun = simdi.weekday()
            saat = simdi.hour * 60 + simdi.minute
            if gun == 0:  # Pazartesi
                bloklar = [("09:00","11:00","TYT Matematik"),("11:15","12:45","Geometri"),("13:45","15:15","TYT Türkçe"),("20:00","20:45","Gece Kapanış")]
            elif gun >= 5:  # Hafta sonu
                bloklar = [("10:00","11:30","Mat Tekrar"),("14:30","16:00","TYT Fen"),("16:15","17:45","TYT Türkçe"),("18:00","19:30","TYT Sosyal")]
            else:  # Salı-Cuma
                bloklar = [("21:00","21:40","TYT Türkçe"),("21:50","22:50","TYT Matematik")]
            for bas, bit, ders in bloklar:
                bh, bm = map(int, bas.split(":")); eh, em = map(int, bit.split(":"))
                if bh*60+bm <= saat <= eh*60+em:
                    return f"📚 ŞU AN DERS VAKTİ: {ders} ({bas}-{bit})"
            sonraki = [(b, ders) for b, bit, ders in bloklar if int(b.split(":")[0])*60+int(b.split(":")[1]) > saat]
            if sonraki:
                b, ders = sonraki[0]
                bh, bm = map(int, b.split(":")); kalan = bh*60+bm-saat
                return f"Sonraki ders {kalan}dk sonra: {ders} ({b})"
            return "Bugün kalan ders yok."

        return f"Bilinmeyen araç: {isim}"
    except Exception as e:
        return f"Hata: {e}"

def groq_sor(mesajlar, sohbet_gecmisi):
    try:
        from groq import Groq
    except ImportError:
        return "Groq yüklü değil: pip install groq"

    anahtar = konfig_al("groq_api_key")
    if not anahtar:
        return "Groq API anahtarı girilmemiş. Ayarlar ekranından girin."

    hafiza  = hafiza_yukle()
    mem_str = hafiza_formatla(hafiza)
    simdi   = datetime.datetime.now()
    sistem  = f"[ZAMAN]\n{simdi.strftime('%A, %d %B %Y — %H:%M')}\n\n"
    if mem_str: sistem += mem_str + "\n\n"
    sistem += SISTEM_PROMPT

    try:
        client = Groq(api_key=anahtar)
        mesaj_listesi = [{"role": "system", "content": sistem}] + sohbet_gecmisi[-16:] + mesajlar

        for _ in range(6):
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=mesaj_listesi,
                tools=GROQ_ARACLAR,
                tool_choice="auto",
                max_tokens=512,
                temperature=0.7,
            )
            msg = resp.choices[0].message

            if not msg.tool_calls:
                return msg.content or "..."

            tc_list = [{"id": tc.id, "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                       for tc in msg.tool_calls]
            mesaj_listesi.append({"role": "assistant", "content": msg.content or "", "tool_calls": tc_list})

            for tc in msg.tool_calls:
                sonuc = araci_calistir(tc.function.name, json.loads(tc.function.arguments or "{}"))
                mesaj_listesi.append({"role": "tool", "tool_call_id": tc.id, "content": str(sonuc)})

        return msg.content or "..."
    except Exception as e:
        traceback.print_exc()
        return f"Hata: {e}"

# ── ElevenLabs TTS ─────────────────────────────────────
def tts_oku(metin: str):
    import requests as _req
    anahtar  = konfig_al("elevenlabs_api_key")
    voice_id = konfig_al("elevenlabs_voice_id")
    if not anahtar or not voice_id: return
    try:
        r = _req.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": anahtar, "Content-Type": "application/json"},
            json={"text": metin, "model_id": "eleven_turbo_v2_5",
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            timeout=20,
        )
        if not r.ok: return
        tmp = BASE / "jarvis_ses.mp3"
        tmp.write_bytes(r.content)
        from kivy.core.audio import SoundLoader
        ses = SoundLoader.load(str(tmp))
        if ses: ses.play()
    except Exception as e:
        print(f"TTS hata: {e}")

# ══════════════════════════════════════════════════════
#  UI BİLEŞENLERİ
# ══════════════════════════════════════════════════════

class TealButton(Button):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.background_normal  = ""
        self.background_color   = TEAL2
        self.color              = TEAL
        self.font_size          = sp(14)
        self.bold               = True
        self.size_hint_y        = None
        self.height             = dp(48)

class MesajBalonu(BoxLayout):
    def __init__(self, metin, kime="jarvis", **kw):
        super().__init__(orientation="vertical", size_hint_y=None, **kw)
        self.padding = [dp(8), dp(4)]

        with self.canvas.before:
            if kime == "sen":
                Color(0.05, 0.45, 0.45, 1)
            else:
                Color(0.04, 0.10, 0.10, 1)
            self._rect = RoundedRectangle(radius=[dp(12)], pos=self.pos, size=self.size)
        self.bind(pos=self._guncelle, size=self._guncelle)

        lbl = Label(
            text=metin,
            font_size=sp(14),
            color=TEAL if kime == "jarvis" else WHITE,
            text_size=(Window.width * 0.72, None),
            halign="left",
            valign="top",
            size_hint_y=None,
            markup=True,
        )
        lbl.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
        lbl.height = lbl.texture_size[1] if lbl.texture_size[1] > 0 else dp(20)
        self.add_widget(lbl)
        self.bind(width=lambda *a: setattr(lbl, "text_size", (self.width - dp(16), None)))
        self.height = lbl.height + dp(16)
        lbl.bind(height=lambda inst, val: setattr(self, "height", val + dp(16)))

    def _guncelle(self, *a):
        self._rect.pos  = self.pos
        self._rect.size = self.size

# ══════════════════════════════════════════════════════
#  EKRANLAR
# ══════════════════════════════════════════════════════

class GirisEkrani(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG); Rectangle(pos=self.pos, size=self.size)

        ana = BoxLayout(orientation="vertical", padding=dp(32), spacing=dp(16))

        ana.add_widget(Widget(size_hint_y=None, height=dp(40)))
        ana.add_widget(Label(text="J.A.R.V.I.S", font_size=sp(36), bold=True, color=TEAL, size_hint_y=None, height=dp(60)))
        ana.add_widget(Label(text="Kişisel AI Asistanı", font_size=sp(14), color=MID, size_hint_y=None, height=dp(30)))
        ana.add_widget(Widget(size_hint_y=None, height=dp(20)))

        ana.add_widget(Label(text="Şifre", font_size=sp(12), color=MID, halign="left", size_hint_y=None, height=dp(24)))
        self.sifre_input = TextInput(
            password=True, multiline=False, font_size=sp(15),
            background_color=BG2, foreground_color=TEAL,
            cursor_color=TEAL, size_hint_y=None, height=dp(48),
            padding=[dp(12), dp(12)],
        )
        self.sifre_input.bind(on_text_validate=self._giris)
        ana.add_widget(self.sifre_input)

        self.hata_lbl = Label(text="", font_size=sp(12), color=RED, size_hint_y=None, height=dp(24))
        ana.add_widget(self.hata_lbl)

        btn = TealButton(text="▸ GİRİŞ YAP")
        btn.bind(on_press=self._giris)
        ana.add_widget(btn)

        ana.add_widget(Widget())
        self.add_widget(ana)

    def on_enter(self):
        # İlk kurulumda şifre yoksa direkt geç
        if not konfig_al("giris_sifresi"):
            self.manager.current = "kurulum"

    def _giris(self, *a):
        import hashlib
        sifre = self.sifre_input.text.strip()
        kayitli = konfig_al("giris_sifresi")
        if hashlib.sha256(sifre.encode()).hexdigest() == kayitli:
            self.hata_lbl.text = ""
            self.manager.transition = SlideTransition(direction="left")
            self.manager.current = "sohbet"
        else:
            self.hata_lbl.text = "⚠ Yanlış şifre!"
            self.sifre_input.text = ""


class KurulumEkrani(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG); Rectangle(pos=self.pos, size=self.size)

        ana = BoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        ana.add_widget(Widget(size_hint_y=None, height=dp(30)))
        ana.add_widget(Label(text="J.A.R.V.I.S", font_size=sp(30), bold=True, color=TEAL, size_hint_y=None, height=dp(50)))
        ana.add_widget(Label(text="İlk Kurulum", font_size=sp(14), color=GOLD, size_hint_y=None, height=dp(24)))
        ana.add_widget(Widget(size_hint_y=None, height=dp(10)))

        alanlar = [
            ("Groq API Anahtarı *", "groq_api_key", True),
            ("ElevenLabs API Anahtarı *", "elevenlabs_api_key", True),
            ("ElevenLabs Voice ID *", "elevenlabs_voice_id", False),
            ("Şifre (en az 4 karakter) *", "_sifre", True),
        ]
        self.inputlar = {}
        for etiket, anahtar, gizli in alanlar:
            ana.add_widget(Label(text=etiket, font_size=sp(11), color=MID, halign="left", size_hint_y=None, height=dp(20)))
            inp = TextInput(
                password=gizli, multiline=False, font_size=sp(13),
                background_color=BG2, foreground_color=TEAL,
                cursor_color=TEAL, size_hint_y=None, height=dp(44),
                padding=[dp(10), dp(10)],
            )
            self.inputlar[anahtar] = inp
            ana.add_widget(inp)

        self.hata = Label(text="", font_size=sp(11), color=RED, size_hint_y=None, height=dp(24))
        ana.add_widget(self.hata)

        btn = TealButton(text="▸ KAYDET VE BAŞLAT")
        btn.bind(on_press=self._kaydet)
        ana.add_widget(btn)
        ana.add_widget(Widget())
        self.add_widget(ana)

    def _kaydet(self, *a):
        import hashlib
        degerler = {k: v.text.strip() for k, v in self.inputlar.items()}
        sifre = degerler.pop("_sifre", "")
        for k, v in degerler.items():
            if not v:
                self.hata.text = "Tüm alanları doldurun!"; return
        if len(sifre) < 4:
            self.hata.text = "Şifre en az 4 karakter olmalı!"; return
        degerler["giris_sifresi"] = hashlib.sha256(sifre.encode()).hexdigest()
        konfig_kaydet(degerler)
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "sohbet"


class SohbetEkrani(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.sohbet_gecmisi = []
        with self.canvas.before:
            Color(*BG); Rectangle(pos=self.pos, size=self.size)

        ana = BoxLayout(orientation="vertical")

        # Header
        header = BoxLayout(size_hint_y=None, height=dp(56),
                           padding=[dp(16), dp(8)], spacing=dp(8))
        with header.canvas.before:
            Color(*BG2); Rectangle(pos=header.pos, size=header.size)
        header.bind(pos=lambda *a: setattr(header.canvas.before.children[-1], 'pos', header.pos),
                    size=lambda *a: setattr(header.canvas.before.children[-1], 'size', header.size))
        header.add_widget(Label(text="J.A.R.V.I.S", font_size=sp(18), bold=True, color=TEAL, halign="left"))
        self.durum_lbl = Label(text="● Hazır", font_size=sp(11), color=MID, halign="right")
        header.add_widget(self.durum_lbl)
        ayar_btn = Button(text="⚙", font_size=sp(20), background_color=BG2,
                          color=MID, size_hint_x=None, width=dp(40))
        ayar_btn.bind(on_press=lambda *a: self._ayarlar_ac())
        header.add_widget(ayar_btn)
        ana.add_widget(header)

        # Hızlı butonlar
        hizli = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6), padding=[dp(8), dp(4)])
        with hizli.canvas.before:
            Color(*BG2); Rectangle(pos=hizli.pos, size=hizli.size)
        hizlilar = [
            ("🌤 Hava", "hava durumu"),
            ("📅 Takvim", "bugün takvimimde ne var?"),
            ("📚 Ders", "şu an ders var mı?"),
            ("🔋 Pil", "pil durumu"),
            ("⏰ Hatırlat", "hatırlatıcılarım neler?"),
        ]
        for etiket, komut in hizlilar:
            btn = Button(
                text=etiket, font_size=sp(11),
                background_normal="", background_color=BG,
                color=TEAL, size_hint_x=None,
                width=dp(80), border=(0,0,0,0),
            )
            btn.bind(on_press=lambda inst, k=komut: self._gonder(k))
            hizli.add_widget(btn)
        ana.add_widget(hizli)

        # Mesajlar
        self.scroll = ScrollView(do_scroll_x=False)
        self.mesaj_listesi = BoxLayout(
            orientation="vertical", size_hint_y=None,
            spacing=dp(8), padding=[dp(12), dp(8)],
        )
        self.mesaj_listesi.bind(minimum_height=self.mesaj_listesi.setter("height"))
        self.scroll.add_widget(self.mesaj_listesi)
        ana.add_widget(self.scroll)

        # Yükleniyor göstergesi
        self.yukleniyor = Label(
            text="JARVIS düşünüyor...", font_size=sp(12),
            color=MID, size_hint_y=None, height=dp(30),
            opacity=0,
        )
        ana.add_widget(self.yukleniyor)

        # Giriş alanı
        alt = BoxLayout(size_hint_y=None, height=dp(60),
                        padding=[dp(12), dp(8)], spacing=dp(8))
        with alt.canvas.before:
            Color(*BG2); Rectangle(pos=alt.pos, size=alt.size)
        self.girdi = TextInput(
            hint_text="Bir şey yaz...", multiline=False,
            font_size=sp(14), background_color=BG,
            foreground_color=TEAL, cursor_color=TEAL,
            hint_text_color=MID, padding=[dp(12), dp(10)],
        )
        self.girdi.bind(on_text_validate=lambda *a: self._gonder())
        alt.add_widget(self.girdi)
        gonder_btn = Button(
            text="➤", font_size=sp(20), bold=True,
            background_normal="", background_color=TEAL2,
            color=TEAL, size_hint_x=None, width=dp(48),
        )
        gonder_btn.bind(on_press=lambda *a: self._gonder())
        alt.add_widget(gonder_btn)
        ana.add_widget(alt)

        self.add_widget(ana)

        # Hoş geldin mesajı
        Clock.schedule_once(lambda dt: self._balon_ekle(
            "Merhaba! Ben JARVIS'im. Size nasıl yardımcı olabilirim?", "jarvis"
        ), 0.5)

    def _balon_ekle(self, metin, kime):
        balon = MesajBalonu(metin, kime)
        if kime == "sen":
            balon.pos_hint = {"right": 1}
        self.mesaj_listesi.add_widget(balon)
        Clock.schedule_once(lambda dt: setattr(self.scroll, "scroll_y", 0), 0.1)

    def _gonder(self, metin=None):
        metin = metin or self.girdi.text.strip()
        if not metin: return
        self.girdi.text = ""
        self._balon_ekle(metin, "sen")
        self.sohbet_gecmisi.append({"role": "user", "content": metin})
        if len(self.sohbet_gecmisi) > 20:
            self.sohbet_gecmisi = self.sohbet_gecmisi[-20:]

        self.yukleniyor.opacity = 1
        self.durum_lbl.text = "● Düşünüyor..."
        self.durum_lbl.color = GOLD

        def _arka_plan():
            mesajlar = [{"role": "user", "content": metin}]
            cevap = groq_sor(mesajlar, self.sohbet_gecmisi[:-1])
            self.sohbet_gecmisi.append({"role": "assistant", "content": cevap})
            Clock.schedule_once(lambda dt: self._cevap_goster(cevap))
            threading.Thread(target=tts_oku, args=(cevap,), daemon=True).start()

        threading.Thread(target=_arka_plan, daemon=True).start()

    def _cevap_goster(self, cevap):
        self.yukleniyor.opacity = 0
        self.durum_lbl.text = "● Hazır"
        self.durum_lbl.color = MID
        self._balon_ekle(cevap, "jarvis")

    def _ayarlar_ac(self):
        self.manager.transition = SlideTransition(direction="left")
        self.manager.current = "ayarlar"


class AyarlarEkrani(Screen):
    def __init__(self, **kw):
        super().__init__(**kw)
        with self.canvas.before:
            Color(*BG); Rectangle(pos=self.pos, size=self.size)

        ana = BoxLayout(orientation="vertical", padding=dp(20), spacing=dp(10))

        # Header
        header = BoxLayout(size_hint_y=None, height=dp(50))
        geri = Button(text="← Geri", background_color=BG, color=TEAL,
                      size_hint_x=None, width=dp(80), font_size=sp(13))
        geri.bind(on_press=lambda *a: self._geri())
        header.add_widget(geri)
        header.add_widget(Label(text="API AYARLARI", font_size=sp(16), bold=True, color=TEAL))
        ana.add_widget(header)

        alanlar = [
            ("Groq API Anahtarı", "groq_api_key", True),
            ("ElevenLabs API Anahtarı", "elevenlabs_api_key", True),
            ("ElevenLabs Voice ID", "elevenlabs_voice_id", False),
        ]
        self.inputlar = {}
        cfg = konfig_yukle()
        for etiket, anahtar, gizli in alanlar:
            ana.add_widget(Label(text=etiket, font_size=sp(11), color=MID,
                                 halign="left", size_hint_y=None, height=dp(20)))
            inp = TextInput(
                text=cfg.get(anahtar, ""), password=gizli,
                multiline=False, font_size=sp(12),
                background_color=BG2, foreground_color=TEAL,
                cursor_color=TEAL, size_hint_y=None, height=dp(42),
                padding=[dp(10), dp(10)],
            )
            self.inputlar[anahtar] = inp
            ana.add_widget(inp)

        self.bilgi = Label(text="", font_size=sp(11), color=TEAL, size_hint_y=None, height=dp(24))
        ana.add_widget(self.bilgi)

        kaydet = TealButton(text="▸ KAYDET")
        kaydet.bind(on_press=self._kaydet)
        ana.add_widget(kaydet)
        ana.add_widget(Widget())
        self.add_widget(ana)

    def on_enter(self):
        cfg = konfig_yukle()
        for k, v in self.inputlar.items():
            v.text = cfg.get(k, "")

    def _kaydet(self, *a):
        degerler = {k: v.text.strip() for k, v in self.inputlar.items()}
        konfig_kaydet(degerler)
        self.bilgi.text = "✅ Kaydedildi!"
        Clock.schedule_once(lambda dt: setattr(self.bilgi, "text", ""), 2)

    def _geri(self):
        self.manager.transition = SlideTransition(direction="right")
        self.manager.current = "sohbet"


# ══════════════════════════════════════════════════════
#  ANA UYGULAMA
# ══════════════════════════════════════════════════════
class JarvisApp(App):
    def build(self):
        Window.clearcolor = BG
        sm = ScreenManager()
        sm.add_widget(GirisEkrani(name="giris"))
        sm.add_widget(KurulumEkrani(name="kurulum"))
        sm.add_widget(SohbetEkrani(name="sohbet"))
        sm.add_widget(AyarlarEkrani(name="ayarlar"))
        sm.current = "giris"
        return sm

    def get_application_name(self):
        return "JARVIS"

if __name__ == "__main__":
    JarvisApp().run()
