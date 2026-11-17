import csv, re, threading, queue, sys, traceback, os, datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Strict first-pass screening. SIC alone cannot establish actual project fit.
CORE_SIC = set("71121 71122 71129 71112 71111 35300 35230".split())
RELATED_SIC = set("43220 42210 42220 35110 35120 35130 35140 35210 35220 72190 74909".split())
STRONG = re.compile(r"\\b(mep|m\\s*&\\s*e|mechanical|hvac|building services|heat networks?|district heating|geothermal|heat pumps?|energy systems|thermal engineering|pipework|piping|plantrooms?|ventilation|renewable energy|heating systems)\\b", re.I)
RELATED = re.compile(r"\\b(engineering|engineers|consultancy|consultants|design|energy|renewables|heating|cooling|utilities|infrastructure)\\b", re.I)
BAD_NAME = re.compile(r"\\b(hairdress|beauty|nail|barber|takeaway|restaurant|pub|retail|fashion|salon|taxi|cleaning|lettings|estate agents?)\\b", re.I)

def field(headers, *candidates):
    normal = lambda s: re.sub("[^a-z0-9]", "", s.lower())
    mapping = {normal(h): h for h in headers}
    return next((mapping[normal(c)] for c in candidates if normal(c) in mapping), None)

def classify(row, name_field, status_field, sic_fields):
    status = (row.get(status_field) or "").strip().lower() if status_field else ""
    if status != "active":
        return False, "Not confirmed active"
    name = (row.get(name_field) or "") if name_field else ""
    if BAD_NAME.search(name):
        return False, "Consumer business"
    codes = []
    for f in sic_fields:
        codes.extend(x.zfill(5) for x in re.findall(r"\\b\\d{4,5}\\b", row.get(f) or ""))
    strong = bool(STRONG.search(name))
    related = bool(RELATED.search(name))
    if any(x in CORE_SIC for x in codes) and (strong or related):
        return True, "Core SIC + relevant name"
    if any(x in RELATED_SIC for x in codes) and strong:
        return True, "Related SIC + specialist name"
    return False, "Insufficient evidence"

def filter_csv(source, dest, events, limit):
    counts = {"priority": 0, "excluded": 0}
    try:
        with open(source, encoding="utf-8-sig", errors="replace", newline="") as f:
            sample = f.read(65536)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\\t|")
            except csv.Error:
                dialect = csv.excel
            reader = csv.DictReader(f, dialect=dialect)
            headers = reader.fieldnames
            if not headers:
                raise ValueError("No CSV headers found")
            name = field(headers, "CompanyName", "Company Name", "name")
            status = field(headers, "CompanyStatus", "Company Status", "status")
            sic = [h for h in headers if "siccode" in re.sub("[^a-z0-9]", "", h.lower())]
            if not sic or not name or not status:
                raise ValueError("Required company name, status or SIC columns missing; check CSV headers.")
            output = Path(dest) / (Path(source).stem + "_synergi_priority.csv")
            if output.resolve() == Path(source).resolve():
                raise ValueError("Output cannot overwrite source")
            with open(output, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=headers + ["SynergiFilterReason"], extrasaction="ignore")
                writer.writeheader()
                for index, row in enumerate(reader, 1):
                    keep, reason = classify(row, name, status, sic)
                    if keep and counts["priority"] < limit:
                        row["SynergiFilterReason"] = reason
                        writer.writerow(row)
                        counts["priority"] += 1
                    else:
                        counts["excluded"] += 1
                    if index % 10000 == 0:
                        events.put(("progress", index, counts.copy()))
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
        self.limit = tk.StringVar(value="5000")
        for title, variable, command in (("Companies House CSV", self.src, self.choose_file), ("Output folder", self.dst, self.choose_folder)):
            ttk.Label(frame, text=title).pack(anchor="w")
            line = ttk.Frame(frame)
            line.pack(fill="x", pady=(3, 12))
            ttk.Entry(line, textvariable=variable).pack(side="left", fill="x", expand=True)
            ttk.Button(line, text="Browse", command=command).pack(side="left", padx=(8, 0))
        ttk.Label(frame, text="Maximum priority leads (first matching rows; not ranked)").pack(anchor="w")
        ttk.Entry(frame, textvariable=self.limit, width=14).pack(anchor="w", pady=(3, 10))
        self.start = ttk.Button(frame, text="Export priority leads only", command=self.run)
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
        try:
            limit = int(self.limit.get())
            if not 1 <= limit <= 100000:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid limit", "Enter a number from 1 to 100000.")
            return
        self.start.configure(state="disabled")
        self.bar.start(10)
        self.status.set("Processing...")
        threading.Thread(target=filter_csv, args=(self.src.get(), self.dst.get(), self.events, limit), daemon=True).start()

    def poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    self.status.set(f"Scanned {event[1]:,} companies; exported {event[2]['priority']:,} priority leads")
                else:
                    self.bar.stop()
                    self.start.configure(state="normal")
                    if event[0] == "error":
                        self.status.set("Error: " + event[1])
                        messagebox.showerror("Error", event[1])
                    else:
                        counts = event[2]
                        msg = f"Scanned {event[1]:,} rows. Exported {counts['priority']:,} priority leads to one CSV in the output folder. This is a strict SIC/name screening, not a ranked list."
                        self.status.set(msg)
                        messagebox.showinfo("Complete", msg)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

def log(message):
    path = Path.home() / "SynergiLeadFilter-startup.log"
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{datetime.datetime.now().isoformat()} {message}\\n")
    return path

if __name__ == "__main__":
    try:
        log("Application started; frozen=" + str(getattr(sys, "frozen", False)))
        if "--self-test" in sys.argv:
            log("Self-test OK; tkinter version=" + str(tk.TkVersion))
            print("SELF TEST OK", flush=True)
            sys.exit(0)
        log("Creating tkinter root")
        root = tk.Tk()
        log("Creating app interface")
        App(root)
        log("Entering mainloop")
        root.mainloop()
        log("Mainloop exited")
    except BaseException:
        details = traceback.format_exc()
        try:
            log("FATAL ERROR\\n" + details)
        except Exception:
            pass
        print(details, file=sys.stderr, flush=True)
        try:
            messagebox.showerror("Synergi Lead Filter startup error", details)
        except Exception:
            pass
        sys.exit(1)
