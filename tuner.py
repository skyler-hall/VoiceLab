"""VoiceLab Tuner: audition voices, tweak them, and save presets.
 
Run:  python tuner.py
"""
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
 
import voicelab as engine
 
# key, label, min, max, step
# Left column: shapes the voice itself
VOICE_SLIDERS = [
    ("blend", "Blend amount  (Kokoro)", 0.0, 1.0, 0.01),
    ("expressiveness", "Expressiveness  (Piper)", 0.0, 1.5, 0.01),
    ("rhythm", "Rhythm wobble  (Piper)", 0.0, 1.5, 0.01),
    ("beep_pitch", "Beep pitch Hz  (Beeps)", 300, 3000, 10),
    ("speed", "Speed", 0.5, 2.0, 0.05),
    ("pitch", "Pitch (semitones)", -12, 12, 0.5),
]
# Right column: effects added on top
EFFECT_SLIDERS = [
    ("metallic", "Metallic shimmer", 0.0, 0.9, 0.01),
    ("tin_size", "Tin can size (ms)", 1.0, 15.0, 0.5),
    ("crunch", "Crunch", 0.0, 1.0, 0.01),
    ("robot_mix", "Robot buzz", 0.0, 1.0, 0.01),
    ("robot_freq", "Robot tone (Hz)", 10, 300, 1),
]
# Third column: where the voice sits between the two speakers
SPACE_SLIDERS = [
    ("pan", "Pan  (left / right)", -1.0, 1.0, 0.05),
    ("width", "Stereo width", 0.0, 1.0, 0.01),
    ("sweep", "Sweep across", -1.0, 1.0, 0.05),
    ("volume", "Volume", 0.2, 2.0, 0.05),
]
NONE = "none"
 
# Japandi palette: washi paper, oak, sumi ink, matcha
C = {
    "washi": "#E7E3DA",   # main background
    "oak": "#D6CBB9",     # side panel, quiet buttons
    "oak_dark": "#BFB09A",
    "field": "#F3F0EA",   # inputs
    "sumi": "#33302C",    # text
    "stone": "#8A847A",   # muted text
    "matcha": "#66734F",  # main action
    "matcha_dark": "#535E40",
}
FONT = "Yu Gothic UI"  # ships with Windows; Tk falls back if missing
 
TEST_LINES = [
    "Hi Skyler! Want to play a video game?",
    "Beep boop! Hello friend! Did you miss me?",
    "Your LeetCode reminder is here. No snoozing this time!",
    "I found three new jobs for you. Should I read them?",
    "Who wants to play video games? Me! I do!",
    "The quick brown fox jumps over the lazy dog.",
]
 
 
class Tuner(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VoiceLab Tuner")
        self.geometry("1280x820")
        self.minsize(1180, 760)
        self.last = None  # (audio, sr) of the last render
        self.vars = {k: tk.DoubleVar(value=engine.DEFAULTS[k])
                     for k, *_ in VOICE_SLIDERS + EFFECT_SLIDERS + SPACE_SLIDERS}
        self.speaker_ids = []
        self.widgets = {}
        self._theme()
 
        left = ttk.Frame(self, padding=(22, 18), style="Main.TFrame")
        right = ttk.Frame(self, padding=(18, 18), style="Side.TFrame")
        right.pack(side="right", fill="y")
        left.pack(side="left", fill="both", expand=True)
 
        self._build_tuner(left)
        self._build_catalog(right)
        self.engine_box.set("kokoro" if engine.kokoro_ready() else "piper")
        self.on_engine()
        self.refresh_catalog()
 
    def _theme(self):
        self.configure(bg=C["washi"])
        st = ttk.Style(self)
        st.theme_use("clam")
        base = (FONT, 10)
        st.configure(".", font=base, background=C["washi"], foreground=C["sumi"],
                     bordercolor=C["oak_dark"], focuscolor=C["matcha"])
        st.configure("Main.TFrame", background=C["washi"])
        st.configure("Side.TFrame", background=C["oak"])
        st.configure("TFrame", background=C["washi"])
        st.configure("TLabel", background=C["washi"])
        st.configure("Side.TLabel", background=C["oak"])
        st.configure("Title.TLabel", font=(FONT, 18), background=C["washi"])
        st.configure("SideTitle.TLabel", font=(FONT, 14), background=C["oak"])
        st.configure("Value.TLabel", foreground=C["matcha_dark"], font=(FONT, 10, "bold"))
        st.configure("Horizontal.TScale", background=C["matcha"], troughcolor=C["oak"],
                     bordercolor=C["washi"], lightcolor=C["matcha"], darkcolor=C["matcha"],
                     gripcount=0, sliderlength=14)
        st.configure("Section.TLabel", font=(FONT, 11, "bold"), foreground=C["matcha_dark"])
        st.configure("Off.TLabel", foreground=C["oak_dark"])
        st.map("Horizontal.TScale", background=[("disabled", C["oak_dark"]), ("active", C["matcha_dark"])])
        st.configure("Muted.TLabel", foreground=C["stone"], font=(FONT, 9))
 
        st.configure("TButton", background=C["oak"], foreground=C["sumi"],
                     borderwidth=0, padding=(14, 6), relief="flat")
        st.map("TButton", background=[("active", C["oak_dark"]), ("pressed", C["oak_dark"])])
        st.configure("Side.TButton", background=C["washi"])
        st.map("Side.TButton", background=[("active", C["field"])])
        st.configure("Accent.TButton", background=C["matcha"], foreground=C["field"],
                     padding=(22, 7), font=(FONT, 10, "bold"))
        st.map("Accent.TButton", background=[("active", C["matcha_dark"]), ("pressed", C["matcha_dark"])])
 
        field = dict(fieldbackground=C["field"], background=C["field"], foreground=C["sumi"],
                     bordercolor=C["oak_dark"], lightcolor=C["field"], darkcolor=C["field"],
                     arrowcolor=C["stone"], padding=4)
        st.configure("TCombobox", **field)
        st.map("TCombobox", fieldbackground=[("disabled", C["oak"]), ("readonly", C["field"])],
               foreground=[("disabled", C["stone"])],
               selectbackground=[("readonly", C["field"])],
               selectforeground=[("readonly", C["sumi"])])
        st.configure("TEntry", **field)
        self.option_add("*TCombobox*Listbox.background", C["field"])
        self.option_add("*TCombobox*Listbox.selectBackground", C["matcha"])
        self.option_add("*TCombobox*Listbox.font", base)
 
    def _slider(self, parent, key, label, lo, hi, step):
        var = self.vars[key]
        box = ttk.Frame(parent)
        top = ttk.Frame(box)
        top.pack(fill="x")
        name = ttk.Label(top, text=label)
        name.pack(side="left")
        shown = ttk.Label(top, style="Value.TLabel")
        shown.pack(side="right")
        places = 0 if step >= 1 else (1 if step >= 0.1 else 2)
 
        def show(*_):
            shown.config(text=f"{var.get():.{places}f}")
 
        def snap(v):
            var.set(round(round(float(v) / step) * step, 3))
 
        var.trace_add("write", show)
        show()
        scale = ttk.Scale(box, from_=lo, to=hi, variable=var, command=snap)
        scale.pack(fill="x", pady=(2, 0))
        self.widgets[key] = (name, shown, scale)
        return box
 
    def _enable(self, key, on):
        name, shown, scale = self.widgets[key]
        scale.state(["!disabled"] if on else ["disabled"])
        name.config(style="TLabel" if on else "Off.TLabel")
        shown.config(style="Value.TLabel" if on else "Off.TLabel")
 
    # ---------- layout ----------
 
    def _row(self, parent, label):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 6))
        ttk.Label(row, text=label, width=9).pack(side="left")
        return row
 
    def _build_tuner(self, f):
        ttk.Label(f, text="VoiceLab", style="Title.TLabel").pack(anchor="w")
        ttk.Label(f, text="Shape a voice, then save it to the catalog.",
                  style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
 
        row = self._row(f, "Engine")
        self.engine_box = ttk.Combobox(row, state="readonly", width=12, values=engine.ENGINES)
        self.engine_box.pack(side="left", padx=5)
        self.engine_box.bind("<<ComboboxSelected>>", lambda e: self.on_engine())
 
        row = self._row(f, "Voice")
        self.voice_box = ttk.Combobox(row, state="readonly", width=40)
        self.voice_box.pack(side="left", padx=5)
        self.voice_box.bind("<<ComboboxSelected>>", lambda e: self.on_voice())
        ttk.Button(row, text="Rescan", command=self.on_engine).pack(side="left")
 
        row = self._row(f, "Speaker")
        self.speaker_box = ttk.Combobox(row, state="readonly", width=30)
        self.speaker_box.pack(side="left", padx=5)
        ttk.Label(row, text="Piper only", style="Muted.TLabel").pack(side="left", padx=6)
 
        row = self._row(f, "Blend with")
        self.blend_box = ttk.Combobox(row, state="readonly", width=30)
        self.blend_box.pack(side="left", padx=5)
        ttk.Label(row, text="Kokoro only", style="Muted.TLabel").pack(side="left", padx=6)
        ttk.Label(f, style="Muted.TLabel",
                  text="Kokoro: af/am = American female/male, bf/bm = British. Beeps: voice picks the beep style."
                  ).pack(anchor="w")
 
        cols = ttk.Frame(f)
        cols.pack(fill="x", pady=(4, 0))
        groups = (("Voice", VOICE_SLIDERS), ("Effects", EFFECT_SLIDERS), ("Space", SPACE_SLIDERS))
        for c, (title, specs) in enumerate(groups):
            cols.columnconfigure(c, weight=1, uniform="c")
            col = ttk.Frame(cols)
            col.grid(row=0, column=c, sticky="new", padx=(0 if c == 0 else 12, 0 if c == 2 else 12))
            ttk.Label(col, text=title, style="Section.TLabel").pack(anchor="w", pady=(6, 0))
            for spec in specs:
                self._slider(col, *spec).pack(fill="x", pady=(6, 0))
 
        ttk.Label(f, text="Test line").pack(anchor="w", pady=(16, 2))
        self.line_box = ttk.Combobox(f, values=TEST_LINES)
        self.line_box.set(TEST_LINES[0])
        self.line_box.pack(fill="x")
 
        row = ttk.Frame(f)
        row.pack(fill="x", pady=8)
        ttk.Button(row, text="Play", style="Accent.TButton", command=self.play).pack(side="left", padx=(0, 6))
        ttk.Button(row, text="Stop", command=engine.stop).pack(side="left", padx=5)
        ttk.Button(row, text="Save WAV", command=self.save_wav).pack(side="left")
        ttk.Button(row, text="Reset sliders", command=self.reset).pack(side="left", padx=5)
        ttk.Button(row, text="Speaker test", command=self.speaker_test).pack(side="left")
 
        holder = ttk.Frame(f)
        holder.pack(fill="x")
        self.piper_get = ttk.Frame(holder)
        row = ttk.Frame(self.piper_get)
        row.pack(fill="x")
        ttk.Label(row, text="Get voice").pack(side="left")
        self.dl_entry = ttk.Entry(row, width=30)
        self.dl_entry.insert(0, "en_US-amy-medium")
        self.dl_entry.pack(side="left", padx=5)
        ttk.Button(row, text="Download", command=self.download_piper).pack(side="left")
        ttk.Label(self.piper_get, text="Hear voices first at rhasspy.github.io/piper-samples",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
 
        self.kokoro_get = ttk.Frame(holder)
        self.kokoro_btn = ttk.Button(self.kokoro_get, text="Download Kokoro (200 MB)",
                                     command=self.download_kokoro)
 
        self.status = ttk.Label(f, text="Ready", style="Muted.TLabel")
        self.status.pack(anchor="w", pady=(8, 0))
 
    def _build_catalog(self, f):
        ttk.Label(f, text="Catalog", style="SideTitle.TLabel").pack(anchor="w", pady=(0, 8))
        self.preset_list = tk.Listbox(f, height=12, width=32, font=(FONT, 10),
                                      bg=C["field"], fg=C["sumi"], bd=0,
                                      highlightthickness=0, activestyle="none",
                                      selectbackground=C["matcha"],
                                      selectforeground=C["field"])
        self.preset_list.pack(fill="y")
        self.preset_list.bind("<Double-Button-1>", lambda e: self.load_preset())
 
        row = ttk.Frame(f, style="Side.TFrame")
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="Load", style="Side.TButton", command=self.load_preset).pack(side="left")
        ttk.Button(row, text="Delete", style="Side.TButton", command=self.delete_preset).pack(side="left", padx=6)
 
        ttk.Label(f, text="Preset name", style="Side.TLabel").pack(anchor="w", pady=(10, 0))
        self.name_entry = ttk.Entry(f, width=32)
        self.name_entry.pack(fill="x")
        ttk.Label(f, text="Tags (comma separated)", style="Side.TLabel").pack(anchor="w", pady=(6, 0))
        self.tags_entry = ttk.Entry(f, width=32)
        self.tags_entry.pack(fill="x")
        ttk.Label(f, text="Notes", style="Side.TLabel").pack(anchor="w", pady=(6, 0))
        self.notes = tk.Text(f, height=5, width=32, font=(FONT, 10), bg=C["field"],
                             fg=C["sumi"], bd=0, highlightthickness=0,
                             insertbackground=C["sumi"], padx=6, pady=4)
        self.notes.pack(fill="x")
        ttk.Button(f, text="Save preset", style="Accent.TButton",
                   command=self.save_preset).pack(fill="x", pady=(12, 0))
 
    # ---------- helpers ----------
 
    def set_status(self, text):
        self.after(0, lambda: self.status.config(text=text))
 
    def run_bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()
 
    def settings(self):
        s = {k: round(v.get(), 3) for k, v in self.vars.items()}
        s["engine"] = self.engine_box.get()
        s["voice"] = self.voice_box.get()
        i = self.speaker_box.current()
        s["speaker"] = self.speaker_ids[i] if 0 <= i < len(self.speaker_ids) else 0
        blend = self.blend_box.get()
        s["blend_voice"] = "" if blend in ("", NONE) else blend
        return s
 
    # ---------- engines and voices ----------
 
    def on_engine(self, after=None):
        eng = self.engine_box.get()
        kok = eng == "kokoro"
        for frame, show in ((self.piper_get, eng == "piper"), (self.kokoro_get, kok)):
            if show:
                frame.pack(fill="x")
            else:
                frame.pack_forget()
        if kok and not engine.kokoro_ready():
            self.kokoro_btn.pack(anchor="w")
        else:
            self.kokoro_btn.pack_forget()
        self.set_status(f"Loading {eng}...")
 
        def work():
            try:
                voices = engine.list_voices(eng)
            except Exception as e:
                self.set_status(f"Could not load {eng}: {e}")
                return
 
            def update():
                self.voice_box["values"] = voices
                if kok:
                    self.blend_box["values"] = [NONE] + voices
                    if self.blend_box.get() not in voices:
                        self.blend_box.set(NONE)
                if not voices:
                    self.voice_box.set("")
                    self.status.config(text="Click Download Kokoro to get started." if kok
                                       else f"No Piper voices yet. Put .onnx files in {engine.VOICES_DIR}")
                elif self.voice_box.get() not in voices:
                    self.voice_box.set("af_heart" if "af_heart" in voices else voices[0])
                if after:
                    after()
                elif voices:
                    self.on_voice()
            self.after(0, update)
        self.run_bg(work)
 
    def on_voice(self, pick=None):
        name = self.voice_box.get()
        if self.engine_box.get() != "piper":
            self.set_status(f"{name} ready")
            return
        self.set_status(f"Loading {name}...")
 
        def work():
            try:
                spk = engine.speakers(name)
            except Exception as e:
                self.set_status(f"Could not load voice: {e}")
                return
 
            def update():
                self.speaker_ids = [i for i, _ in spk]
                self.speaker_box["values"] = [f"{i}: {n}" for i, n in spk]
                idx = self.speaker_ids.index(pick) if pick in self.speaker_ids else 0
                self.speaker_box.current(idx)
                self.status.config(text=f"{name}: {len(spk)} speaker(s)")
            self.after(0, update)
        self.run_bg(work)
 
    def download_piper(self):
        name = self.dl_entry.get().strip()
        if not name:
            return
        self.set_status(f"Downloading {name}...")
 
        def work():
            r = subprocess.run([sys.executable, "-m", "piper.download_voices", name,
                                "--download-dir", str(engine.VOICES_DIR)],
                               capture_output=True, text=True)
            if r.returncode == 0:
                self.set_status(f"Downloaded {name}")
                self.after(0, self.on_engine)
            else:
                self.set_status(f"Download failed: {(r.stderr or r.stdout).strip()[-120:]}")
        self.run_bg(work)
 
    def download_kokoro(self):
        def work():
            try:
                engine.download_kokoro(self.set_status)
            except Exception as e:
                self.set_status(f"Download failed: {e}")
                return
            self.set_status("Kokoro downloaded")
            self.after(0, self.on_engine)
        self.run_bg(work)
 
    # ---------- audio ----------
 
    def play(self):
        s, text = self.settings(), self.line_box.get().strip()
        if not s["voice"] or not text:
            return
        self.set_status("Rendering...")
 
        def work():
            try:
                t0 = time.perf_counter()
                audio, sr = engine.render_stereo(s, text)
                took = time.perf_counter() - t0
            except Exception as e:
                self.set_status(f"Error: {e}")
                return
            self.last = (audio, sr)
            self.set_status(f"Rendered in {took:.2f}s for {len(audio) / sr:.1f}s of speech")
            engine.play(audio, sr, wait=False)
        self.run_bg(work)
 
    def speaker_test(self):
        """Says left in the left speaker, right in the right one."""
        s = self.settings()
        if not s["voice"]:
            return
 
        def work():
            try:
                for word, side in (("Left", -1.0), ("Right", 1.0), ("Both", 0.0)):
                    self.set_status(f"Speaker test: {word.lower()}")
                    audio, sr = engine.render_stereo(s, word, pan=side, sweep=0.0)
                    engine.play(audio, sr, wait=True)
                self.set_status("Speaker test done")
            except Exception as e:
                self.set_status(f"Error: {e}")
        self.run_bg(work)
 
    def save_wav(self):
        if not self.last:
            messagebox.showinfo("VoiceLab", "Play something first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".wav",
                                            filetypes=[("WAV", "*.wav")])
        if path:
            engine.save_wav(*self.last, path)
            self.set_status(f"Saved {path}")
 
    def reset(self):
        for k, v in self.vars.items():
            v.set(engine.DEFAULTS[k])
        if self.engine_box.get() == "kokoro":
            self.blend_box.set(NONE)
 
    # ---------- catalog ----------
 
    def refresh_catalog(self):
        self.preset_list.delete(0, "end")
        for name, p in sorted(engine.load_catalog()["presets"].items()):
            tags = ", ".join(p.get("tags", []))
            self.preset_list.insert("end", f"{name}  [{tags}]" if tags else name)
 
    def selected_preset(self):
        sel = self.preset_list.curselection()
        return self.preset_list.get(sel[0]).split("  [")[0] if sel else None
 
    def save_preset(self):
        name = self.name_entry.get().strip()
        if not name:
            messagebox.showinfo("VoiceLab", "Give the preset a name first.")
            return
        if name in engine.load_catalog()["presets"] and not messagebox.askyesno(
                "VoiceLab", f"'{name}' already exists. Overwrite it?"):
            return
        tags = [t.strip() for t in self.tags_entry.get().split(",") if t.strip()]
        engine.save_preset(name, self.settings(), self.notes.get("1.0", "end").strip(), tags)
        self.refresh_catalog()
        self.set_status(f"Saved preset '{name}'")
 
    def load_preset(self):
        name = self.selected_preset()
        if not name:
            return
        p = engine.load_catalog()["presets"][name]
        s = {**engine.DEFAULTS, **p["settings"]}
        for k, v in self.vars.items():
            v.set(s[k])
        self.engine_box.set(s["engine"])
 
        def apply():
            if s["voice"] not in self.voice_box["values"]:
                self.set_status(f"Voice {s['voice']} is missing. Download it first.")
                return
            self.voice_box.set(s["voice"])
            if s["engine"] == "kokoro":
                self.blend_box.set(s["blend_voice"] or NONE)
                self.set_status(f"Loaded {name}")
            else:
                self.on_voice(pick=s["speaker"])
        self.on_engine(after=apply)
        self.name_entry.delete(0, "end")
        self.name_entry.insert(0, name)
        self.tags_entry.delete(0, "end")
        self.tags_entry.insert(0, ", ".join(p.get("tags", [])))
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", p.get("notes", ""))
 
    def delete_preset(self):
        name = self.selected_preset()
        if name and messagebox.askyesno("VoiceLab", f"Delete '{name}'?"):
            engine.delete_preset(name)
            self.refresh_catalog()
 
 
if __name__ == "__main__":
    app = Tuner()
    # Minimize and restore once so Windows doesn't close the window on startup
    app.iconify()
    app.update()
    app.deiconify()
    app.mainloop()
 
