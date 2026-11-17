import csv, re, threading, queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Conservative first-pass lead screening. Review uncertain results before discarding.
PRIORITY = set("71111 71112 71121 71122 71129 71120 43220 43210 43290 42210 42220 42910 42990 35300 35110 35120 35130 35140 35210 35220 35230 43999 41201 41202 41100 72190 74901 74909".split())
POTENTIAL = set("25110 25210 25290 28110 28120 28130 28140 28150 28210 28220 28250 28290 28990 33110 33120 33140 33190 33200 36000 37000 38110 38210 39000 42110 42120 42130 43110 43120 43130 43140 43150 43160 43170 43180 43190 43390 43910 43991 43992 68100 68209 68320 70229 71200 72110 74100 74902 77320".split())
EXCLUDE = set("01 02 03 10 11 12 13 14 15 16 17 18 45 46 47 49 50 51 52 53 55 56 58 59 60 61 62 63 64 65 66 69 73 74 75 77 78 79 80 81 82 84 85 86 87 88 90 91 92 93 94 95 96 97 98 99".split())
KEYWORDS = re.compile(r"\b(engineer\w*|mechanical|mep|hvac|heating|heat\s*(?:pump|network)|district\s*heat|geothermal|renewable|thermal|pipe\w*|plant\s*room|building\s*services|infrastructure|industrial|construction|developer|solar|utilities|fabrication|data\s*cent(?:er|re)|cooling|ventilation)\b", re.I)

def field(headers, *candidates):
    normal = lambda s: re.sub("[^a-z0-9]", "", s.lower())
    mapping = {normal(h): h for h in headers}
    return next((mapping[normal(c)] for c in candidates if normal(c) in mapping), None)

def classify(row, name_field, status_field, sic_fields):
    status = (row.get(status_field) or "").strip().lower() if status_field else ""
    if status and status not in ("active", "open"):
        return "excluded", "Inactive company"
    codes = []
    for f in sic_fields:
        codes.extend(x.zfill(5) for x in re.findall(r"\b\d{4,5}\b", row.get(f) or ""))
    if any(x in PRIORITY for x in codes):
        return "priority", "Relevant SIC code"
    if any(x in POTENTIAL for x in codes):
        return "potential", "Adjacent SIC code"
    if KEYWORDS.search(row.get(name_field) or "") if name_field else False:
        return "potential", "Relevant company name"
    if codes and all(x[:2] in EXCLUDE for x in codes):
        return "excluded", "Unrelated SIC sector"
    return "review", "Uncertain classification"

def filter_csv(source, dest, events):
    counts = dict.fromkeys(("priority", "potential", "review", "excluded"), 0)
    outputs = {}
    try:
        with open(source, encoding="utf-8-sig", errors="replace", newline="") as f:
            sample = f.read(65536)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            headers = reader.fieldnames
            if not headers:
                raise ValueError("No CSV headers found")
            name = field(headers, "CompanyName", "Company Name", "name")
            status = field(headers, "CompanyStatus", "Company Status", "status")
            sic = [h for h in headers if "siccode" in re.sub("[^a-z0-9]", "", h.lower())]
            if not sic:
                raise ValueError("No SIC code columns found. Please provide your CSV headers.")
            try:
                for tier in ("priority", "potential", "review"):
                    path = Path(dest) / (Path(source).stem + "_synergi_" + tier + ".csv")
                    if path.resolve() == Path(source).resolve():
                        raise ValueError("Output cannot overwrite source")
                    handle = open(path, "w", encoding="utf-8-sig", newline="")
                    writer = csv.DictWriter(handle, fieldnames=headers + ["SynergiLeadTier", "SynergiFilterReason"], extrasaction="ignore")
                    writer.writeheader()
                    outputs[tier] = (handle, writer)
                for index, row in enumerate(reader, 1):
                    tier, reason = classify(row, name, status, sic)
                    counts[tier] += 1
                    if tier in outputs:
                        row["SynergiLeadTier"] = tier
                        row["SynergiFilterReason"] = reason
                        outputs[tier][1].writerow(row)
                    if index % 10000 == 0:
                        events.put(("progress", index, counts.copy()))
            finally:
                for handle, _ in outputs.values():
                    handle.close()
        events.put(("done", index if 'index' in locals() else 0, counts))
    except Exception as exc:
        events.put(("error", str(exc)))

class App:
    def __init__(self, root):
        self.root = root
        root.title("Synergi | Companies House Lead Filter")
        root.geometry("700x370")
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Companies House Lead Filter", font=("Segoe UI", 17, "bold")).pack(anchor="w", pady=(0, 15))
        self.src, self.dst = tk.StringVar(), tk.StringVar()
        for title, variable, command in (("Companies House CSV", self.src, self.choose_file), ("Output folder", self.dst, self.choose_folder)):
            ttk.Label(frame, text=title).pack(anchor="w")
            line = ttk.Frame(frame)
            line.pack(fill="x", pady=(3, 12))
            ttk.Entry(line, textvariable=variable).pack(side="left", fill="x", expand=True)
            ttk.Button(line, text="Browse", command=command).pack(side="left", padx=(8, 0))
        self.start = ttk.Button(frame, text="Filter companies", command=self.run)
        self.start.pack(anchor="w")
        self.bar = ttk.Progressbar(frame, mode="indeterminate")
        self.bar.pack(fill="x", pady=(18, 8))
        self.status = tk.StringVar(value="Ready. Your original CSV will not be modified. All processing stays on this computer.")
        ttk.Label(frame, textvariable=self.status, wraplength=650).pack(anchor="w")
        self.events = queue.Queue()
        root.after(100, self.poll)

    def choose_file(self):
        path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if path:
            self.src.set(path)
            self.dst.set(str(Path(path).parent))

    def choose_folder(self):
        path = filedialog.askdirectory()
        if path:
            self.dst.set(path)

    def run(self):
        if not Path(self.src.get()).is_file() or not Path(self.dst.get()).is_dir():
            messagebox.showerror("Missing path", "Select a CSV file and an existing output folder.")
            return
        self.start.configure(state="disabled")
        self.bar.start(10)
        self.status.set("Processing...")
        threading.Thread(target=filter_csv, args=(self.src.get(), self.dst.get(), self.events), daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    self.status.set(f"Processed {event[1]:,} companies; priority {event[2]['priority']:,}; potential {event[2]['potential']:,}; review {event[2]['review']:,}")
                else:
                    self.bar.stop()
                    self.start.configure(state="normal")
                    if event[0] == "error":
                        self.status.set("Error: " + event[1])
                        messagebox.showerror("Error", event[1])
                    else:
                        counts = event[2]
                        msg = f"Finished {event[1]:,} rows. Priority: {counts['priority']:,}; potential: {counts['potential']:,}; review: {counts['review']:,}; excluded: {counts['excluded']:,}. Files saved to the output folder."
                        self.status.set(msg)
                        messagebox.showinfo("Complete", msg)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

if __name__ == "__main__":
    root = tk.Tk()
    App(root)
