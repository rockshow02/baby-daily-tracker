import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import { toUserFacingErrorMessage } from "../utils/errorMessage";

const inputClass =
  "w-full rounded-2xl border border-void-hairline bg-white px-4 py-3.5 text-sm text-ink shadow-sm placeholder:text-ink-faint focus:border-feed";

export default function AuthScreen() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const switchMode = (nextMode) => {
    setMode(nextMode);
    setError("");
  };

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(name, email, password);
    } catch (err) {
      setError(toUserFacingErrorMessage(err, "Belum berhasil memproses akun. Coba lagi."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="app-page flex min-h-screen items-center px-5 py-8">
      <div className="mx-auto w-full max-w-sm">
        <section className="relative mb-6 overflow-hidden rounded-[2rem] bg-gradient-to-br from-feed-soft via-white to-sleep-soft px-6 py-7 text-center shadow-soft">
          <span className="absolute -left-5 -top-5 h-24 w-24 rounded-full bg-feed/10" aria-hidden="true" />
          <span className="absolute -bottom-8 -right-5 h-28 w-28 rounded-full bg-sleep/10" aria-hidden="true" />
          <span className="relative inline-flex h-16 w-16 items-center justify-center rounded-full bg-white text-4xl shadow-soft" aria-hidden="true">👶</span>
          <p className="relative mt-4 text-[11px] font-bold uppercase tracking-[0.22em] text-feed">Baby Daily Tracker</p>
          <h1 className="relative mt-2 font-display text-3xl leading-tight text-ink">
            {mode === "login" ? "Selamat datang kembali" : "Mulai catatan si kecil"}
          </h1>
          <p className="relative mt-2 text-sm leading-relaxed text-ink-muted">
            {mode === "login"
              ? "Semua rutinitas penting, tersimpan rapi dalam satu tempat."
              : "Buat akun untuk mencatat rutinitas dan tumbuh kembang bersama pengasuh."}
          </p>
        </section>

        <div className="mb-4 grid grid-cols-2 rounded-2xl bg-void-raised p-1" aria-label="Pilih akses akun">
          {[{ key: "login", label: "Masuk" }, { key: "register", label: "Daftar" }].map((item) => (
            <button
              key={item.key}
              type="button"
              aria-pressed={mode === item.key}
              onClick={() => switchMode(item.key)}
              className={`rounded-xl py-2.5 text-sm font-bold transition ${
                mode === item.key ? "bg-white text-feed shadow-sm" : "text-ink-muted"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} className="soft-card space-y-4 p-5">
          {mode === "register" && (
            <label className="block text-xs font-bold text-ink-muted">
              Nama Anda
              <input type="text" autoComplete="name" placeholder="Contoh: Alya" value={name} onChange={(event) => setName(event.target.value)} className={`${inputClass} mt-1.5`} required />
            </label>
          )}
          <label className="block text-xs font-bold text-ink-muted">
            Email
            <input type="email" autoComplete="email" placeholder="nama@email.com" value={email} onChange={(event) => setEmail(event.target.value)} className={`${inputClass} mt-1.5`} required />
          </label>
          <label className="block text-xs font-bold text-ink-muted">
            Password
            <span className="relative mt-1.5 block">
              <input type={showPassword ? "text" : "password"} autoComplete={mode === "login" ? "current-password" : "new-password"} placeholder="Minimal 6 karakter" value={password} onChange={(event) => setPassword(event.target.value)} className={`${inputClass} pr-16`} required minLength={6} />
              <button type="button" onClick={() => setShowPassword((value) => !value)} className="absolute inset-y-0 right-3 text-[11px] font-bold text-feed" aria-label={showPassword ? "Sembunyikan password" : "Tampilkan password"}>
                {showPassword ? "Tutup" : "Lihat"}
              </button>
            </span>
          </label>

          {error && <p role="alert" className="rounded-2xl bg-warn-soft px-3.5 py-3 text-sm font-semibold text-warn">{error}</p>}

          <button type="submit" disabled={loading} className="w-full rounded-2xl bg-feed py-3.5 text-sm font-extrabold text-white shadow-soft transition active:scale-[0.99] disabled:opacity-50">
            {loading ? "Memproses..." : mode === "login" ? "Masuk ke aplikasi" : "Buat akun"}
          </button>
        </form>

        <p className="mt-5 text-center text-xs leading-relaxed text-ink-faint">Data akun dipakai hanya untuk menjaga catatan keluarga tetap aman dan terpisah.</p>
      </div>
    </main>
  );
}
