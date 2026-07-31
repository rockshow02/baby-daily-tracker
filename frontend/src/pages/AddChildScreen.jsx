import { useState } from "react";
import { api } from "../api/client";

export default function AddChildScreen({ onCreated }) {
  const [name, setName] = useState("");
  const [birthDate, setBirthDate] = useState("");
  const [gender, setGender] = useState("L");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const child = await api.createChild({ name, birth_date: birthDate, gender });
      onCreated(child);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <p className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-2">Langkah pertama</p>
          <h1 className="font-display text-3xl text-ink">Siapa yang kita pantau?</h1>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="text"
            placeholder="Nama anak"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full bg-void-card border border-void-hairline rounded-lg px-4 py-3 text-ink placeholder:text-ink-faint"
            required
          />
          <div>
            <label className="block text-xs text-ink-muted mb-1.5 ml-1">Tanggal lahir</label>
            <input
              type="date"
              value={birthDate}
              onChange={(e) => setBirthDate(e.target.value)}
              max={new Date().toISOString().split("T")[0]}
              className="w-full bg-void-card border border-void-hairline rounded-lg px-4 py-3 text-ink"
              required
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            {[
              ["L", "Laki-laki"],
              ["P", "Perempuan"],
            ].map(([val, label]) => (
              <button
                type="button"
                key={val}
                onClick={() => setGender(val)}
                className={`py-3 rounded-lg text-sm border ${
                  gender === val ? "bg-feed/20 border-feed text-feed" : "border-void-hairline text-ink-muted"
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {error && <p className="text-warn text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3.5 rounded-lg bg-feed text-void font-semibold mt-2 disabled:opacity-50"
          >
            {loading ? "Menyimpan..." : "Mulai Catat"}
          </button>
        </form>
      </div>
    </div>
  );
}
