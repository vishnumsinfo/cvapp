import { useState, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

const REC_STYLE = {
  strong: "bg-emerald-100 text-emerald-700 border-emerald-200",
  maybe: "bg-amber-100 text-amber-700 border-amber-200",
  reject: "bg-rose-100 text-rose-700 border-rose-200",
};

function scoreColor(s) {
  if (s >= 75) return "text-emerald-600";
  if (s >= 50) return "text-amber-600";
  return "text-rose-600";
}

export default function Dashboard() {
  const [jobs, setJobs] = useState([]);
  const [activeJob, setActiveJob] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [sortBy, setSortBy] = useState("score");
  const [recFilter, setRecFilter] = useState("all");
  const [showJobForm, setShowJobForm] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [drag, setDrag] = useState(false);

  const loadJobs = useCallback(async () => {
    const r = await fetch(`${API}/jobs`);
    const data = await r.json();
    setJobs(data);
    if (!activeJob && data.length) setActiveJob(data[0]);
  }, [activeJob]);

  const loadCandidates = useCallback(async () => {
    if (!activeJob) return;
    const r = await fetch(`${API}/candidates?job_id=${activeJob.id}`);
    setCandidates(await r.json());
  }, [activeJob]);

  useEffect(() => { loadJobs(); }, []);
  useEffect(() => { loadCandidates(); }, [activeJob]);

  // poll while any candidate is still processing
  useEffect(() => {
    const pending = candidates.some((c) => ["pending", "processing"].includes(c.status));
    if (!pending) return;
    const t = setInterval(loadCandidates, 3000);
    return () => clearInterval(t);
  }, [candidates, loadCandidates]);

  async function handleFiles(fileList) {
    if (!activeJob) return alert("Create or select a job first.");
    const fd = new FormData();
    [...fileList].forEach((f) => fd.append("files", f));
    setUploading(true);
    try {
      await fetch(`${API}/upload?job_id=${activeJob.id}`, { method: "POST", body: fd });
      await loadCandidates();
    } finally {
      setUploading(false);
    }
  }

  async function openDetail(c) {
    setSelected(c.id);
    const r = await fetch(`${API}/candidates/${c.id}`);
    setDetail(await r.json());
  }

  const filtered = candidates
    .filter((c) => recFilter === "all" || c.evaluation?.recommendation === recFilter)
    .sort((a, b) => {
      if (sortBy === "score")
        return (b.evaluation?.match_score || 0) - (a.evaluation?.match_score || 0);
      return (a.full_name || a.file_name).localeCompare(b.full_name || b.file_name);
    });

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      {/* Header */}
      <header className="border-b border-slate-200 bg-white px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-indigo-600 grid place-items-center text-white font-bold">CV</div>
          <h1 className="text-lg font-semibold">Resume Screener</h1>
        </div>
        <button
          onClick={() => setShowJobForm((v) => !v)}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          + New Job
        </button>
      </header>

      <div className="grid grid-cols-12 gap-6 p-6">
        {/* Left: jobs */}
        <aside className="col-span-3 space-y-2">
          <h2 className="text-xs font-semibold uppercase text-slate-400 mb-2">Jobs</h2>
          {jobs.map((j) => (
            <button
              key={j.id}
              onClick={() => { setActiveJob(j); setDetail(null); setSelected(null); }}
              className={`w-full rounded-lg border px-3 py-2 text-left text-sm ${
                activeJob?.id === j.id
                  ? "border-indigo-300 bg-indigo-50"
                  : "border-slate-200 bg-white hover:bg-slate-50"
              }`}
            >
              <div className="font-medium">{j.title}</div>
              <div className="text-xs text-slate-400">
                {(j.required_skills || []).slice(0, 3).join(", ")}
              </div>
            </button>
          ))}
          {showJobForm && <JobForm api={API} onCreated={() => { setShowJobForm(false); loadJobs(); }} />}
        </aside>

        {/* Middle: candidates */}
        <main className="col-span-5 space-y-4">
          {/* uploader */}
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); handleFiles(e.dataTransfer.files); }}
            className={`rounded-xl border-2 border-dashed p-6 text-center text-sm transition ${
              drag ? "border-indigo-400 bg-indigo-50" : "border-slate-300 bg-white"
            }`}
          >
            <p className="text-slate-500">
              {uploading ? "Uploading…" : "Drag & drop PDF / DOCX resumes here"}
            </p>
            <label className="mt-2 inline-block cursor-pointer text-indigo-600 font-medium">
              or browse
              <input
                type="file" multiple accept=".pdf,.docx,.doc" hidden
                onChange={(e) => handleFiles(e.target.files)}
              />
            </label>
          </div>

          {/* controls */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex gap-2">
              {["all", "strong", "maybe", "reject"].map((r) => (
                <button
                  key={r}
                  onClick={() => setRecFilter(r)}
                  className={`rounded-md px-3 py-1 text-xs capitalize ${
                    recFilter === r ? "bg-slate-800 text-white" : "bg-white border border-slate-200"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <select
                value={sortBy} onChange={(e) => setSortBy(e.target.value)}
                className="rounded-md border border-slate-200 px-2 py-1 text-xs"
              >
                <option value="score">Sort: Score</option>
                <option value="name">Sort: Name</option>
              </select>
              <a
                href={`${API}/export?job_id=${activeJob?.id || 0}`}
                className="rounded-md bg-emerald-600 px-3 py-1 text-xs font-medium text-white"
              >
                Export CSV
              </a>
            </div>
          </div>

          {/* list */}
          <div className="space-y-2">
            {filtered.map((c) => (
              <div
                key={c.id}
                onClick={() => openDetail(c)}
                className={`cursor-pointer rounded-lg border bg-white p-3 hover:shadow-sm ${
                  selected === c.id ? "border-indigo-300" : "border-slate-200"
                }`}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium">{c.full_name || c.file_name}</div>
                    <div className="text-xs text-slate-400">{c.email || c.file_name}</div>
                  </div>
                  {c.status === "done" && c.evaluation ? (
                    <div className="flex items-center gap-2">
                      <span className={`text-lg font-bold ${scoreColor(c.evaluation.match_score)}`}>
                        {Math.round(c.evaluation.match_score)}%
                      </span>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase ${REC_STYLE[c.evaluation.recommendation]}`}>
                        {c.evaluation.recommendation}
                      </span>
                    </div>
                  ) : (
                    <span className="text-xs text-slate-400 capitalize">{c.status}</span>
                  )}
                </div>
              </div>
            ))}
            {!filtered.length && (
              <p className="py-8 text-center text-sm text-slate-400">No candidates yet.</p>
            )}
          </div>
        </main>

        {/* Right: detail */}
        <section className="col-span-4">
          {detail ? <CandidateDetail d={detail} /> : (
            <div className="rounded-xl border border-slate-200 bg-white p-6 text-center text-sm text-slate-400">
              Select a candidate to view the scorecard.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function CandidateDetail({ d }) {
  const ev = d.evaluation;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 space-y-4 sticky top-6">
      <div>
        <h3 className="text-lg font-semibold">{d.full_name || d.file_name}</h3>
        <p className="text-xs text-slate-400">{d.email} · {d.phone}</p>
      </div>
      {!ev ? (
        <p className="text-sm text-slate-400 capitalize">Status: {d.status}. {d.error_message}</p>
      ) : (
        <>
          <div className="grid grid-cols-4 gap-2 text-center">
            {[["Match", ev.match_score], ["Skills", ev.skill_alignment],
              ["Exp", ev.experience_depth], ["Relev", ev.relevancy]].map(([k, v]) => (
              <div key={k} className="rounded-lg bg-slate-50 p-2">
                <div className={`text-base font-bold ${scoreColor(v)}`}>{Math.round(v)}</div>
                <div className="text-[10px] uppercase text-slate-400">{k}</div>
              </div>
            ))}
          </div>

          <Block title="Fit Analysis"><p className="text-sm text-slate-600">{ev.fit_analysis}</p></Block>

          {!!ev.missing_critical_skills?.length && (
            <Block title="Missing Critical Skills">
              <Chips items={ev.missing_critical_skills} cls="bg-rose-50 text-rose-600" />
            </Block>
          )}
          {!!ev.red_flags?.length && (
            <Block title="Red Flags">
              <ul className="list-disc pl-4 text-sm text-rose-600 space-y-1">
                {ev.red_flags.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            </Block>
          )}
          <Block title="Recommended Interview Questions">
            <ol className="list-decimal pl-4 text-sm text-slate-600 space-y-1">
              {ev.interview_questions.map((q, i) => <li key={i}>{q}</li>)}
            </ol>
          </Block>
          {d.parsed_data?.technical_skills?.length > 0 && (
            <Block title="Technical Skills">
              <Chips items={d.parsed_data.technical_skills} cls="bg-indigo-50 text-indigo-600" />
            </Block>
          )}
        </>
      )}
    </div>
  );
}

const Block = ({ title, children }) => (
  <div>
    <h4 className="mb-1 text-xs font-semibold uppercase text-slate-400">{title}</h4>
    {children}
  </div>
);

const Chips = ({ items, cls }) => (
  <div className="flex flex-wrap gap-1">
    {items.map((s, i) => (
      <span key={i} className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>{s}</span>
    ))}
  </div>
);

function JobForm({ api, onCreated }) {
  const [f, setF] = useState({ title: "", description: "", required_skills: "", min_experience_years: 0 });
  async function submit() {
    await fetch(`${api}/jobs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: f.title,
        description: f.description,
        min_experience_years: Number(f.min_experience_years),
        required_skills: f.required_skills.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    });
    onCreated();
  }
  return (
    <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 space-y-2">
      <input className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
        placeholder="Job title" value={f.title}
        onChange={(e) => setF({ ...f, title: e.target.value })} />
      <textarea className="w-full rounded border border-slate-200 px-2 py-1 text-sm" rows={3}
        placeholder="Description" value={f.description}
        onChange={(e) => setF({ ...f, description: e.target.value })} />
      <input className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
        placeholder="Required skills (comma separated)" value={f.required_skills}
        onChange={(e) => setF({ ...f, required_skills: e.target.value })} />
      <input type="number" className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
        placeholder="Min experience (years)" value={f.min_experience_years}
        onChange={(e) => setF({ ...f, min_experience_years: e.target.value })} />
      <button onClick={submit}
        className="w-full rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white">
        Create Job
      </button>
    </div>
  );
}
