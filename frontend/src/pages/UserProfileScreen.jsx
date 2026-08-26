import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";
import { describeRole, isOwner } from "../utils/roles";

export default function UserProfileScreen({ user, onUserUpdated }) {
  const [name, setName] = useState(user.name);
  const [telegramChatId, setTelegramChatId] = useState(user.telegram_chat_id || "");
  const [savingTelegram, setSavingTelegram] = useState(false);
  const [telegramSaved, setTelegramSaved] = useState(false);
  const [telegramError, setTelegramError] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameSaved, setNameSaved] = useState(false);
  const [nameError, setNameError] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordError, setPasswordError] = useState("");
  const [passwordSaved, setPasswordSaved] = useState(false);

  const [childrenRoles, setChildrenRoles] = useState([]);
  const [loadingRoles, setLoadingRoles] = useState(true);

  const load = useCallback(async () => {
    setLoadingRoles(true);
    try {
      // Caregiver Roles & Permissions Phase 1 — api.listChildren() UDAH
      // nyertain `role` (peran EFEKTIF user yang login) langsung di
      // respons-nya (lihat backend/docs/ROLES_PERMISSIONS.md). SEBELUMNYA
      // layar ini nge-derive peran sendiri lewat api.listCaregivers(c.id)
      // per anak (N+1 request) + nyari user_id di daftar caregiver-nya —
      // itu asumsi BASI dari sebelum owner selalu ada baris
      // ChildCaregiver-nya sendiri; sekarang cukup pakai `role` yang
      // udah dikembalikan langsung, nggak perlu request tambahan sama
      // sekali.
      setChildrenRoles(await api.listChildren());
    } finally {
      setLoadingRoles(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSaveName = async (e) => {
    e.preventDefault();
    setNameError("");
    setNameSaved(false);
    setSavingName(true);
    try {
      const updated = await api.updateProfile({ name });
      onUserUpdated(updated);
      setNameSaved(true);
      setTimeout(() => setNameSaved(false), 2000);
    } catch (err) {
      setNameError(err.message);
    } finally {
      setSavingName(false);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setPasswordError("");
    setPasswordSaved(false);
    setSavingPassword(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setPasswordSaved(true);
      setTimeout(() => setPasswordSaved(false), 2000);
    } catch (err) {
      setPasswordError(err.message);
    } finally {
      setSavingPassword(false);
    }
  };

  const handleSaveTelegram = async (e) => {
    e.preventDefault();
    setTelegramError("");
    setTelegramSaved(false);
    setTestResult("");
    setSavingTelegram(true);
    try {
      const updated = await api.updateProfile({ telegram_chat_id: telegramChatId });
      onUserUpdated(updated);
      setTelegramSaved(true);
      setTimeout(() => setTelegramSaved(false), 2000);
    } catch (err) {
      setTelegramError(err.message);
    } finally {
      setSavingTelegram(false);
    }
  };

  const handleTestTelegram = async () => {
    setTestResult("");
    setTesting(true);
    try {
      await api.testTelegram();
      setTestResult("✓ Berhasil! Cek chat Telegram kamu.");
    } catch (err) {
      setTestResult("✗ " + err.message);
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="min-h-screen px-4 pb-28 pt-6 sm:px-6 sm:pt-8">
      <header className="mb-5 overflow-hidden rounded-xl2 bg-gradient-to-br from-feed-soft via-white to-sleep-soft p-5 shadow-soft">
        <div className="flex items-center gap-4">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-white text-2xl font-bold uppercase text-feed shadow-sm" aria-hidden="true">
            {(user.name || user.email || "U").charAt(0)}
          </div>
          <div className="min-w-0">
            <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-feed">Akun pengasuh</p>
            <h1 className="truncate font-display text-2xl font-bold text-ink">{user.name}</h1>
            <p className="truncate text-xs text-ink-muted">{user.email}</p>
          </div>
        </div>
      </header>

      <section className="mb-4 rounded-xl2 border border-void-hairline bg-void-card p-4 shadow-soft sm:p-5">
        <div className="mb-3">
          <h2 className="text-base font-bold text-ink">Informasi akun</h2>
          <p className="text-xs text-ink-faint">Nama ini terlihat oleh pengasuh lain.</p>
        </div>
        <form onSubmit={handleSaveName} className="flex flex-col gap-2 min-[380px]:flex-row">
          <label htmlFor="profile-name" className="sr-only">Nama</label>
          <input
            id="profile-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="min-w-0 flex-1 rounded-xl border border-void-hairline bg-void px-3 py-3 text-sm text-ink"
            required
          />
          <button
            type="submit"
            disabled={savingName}
            className="whitespace-nowrap rounded-xl bg-feed px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            {savingName ? "..." : nameSaved ? "Tersimpan ✓" : "Simpan"}
          </button>
        </form>
        {nameError && <p className="mt-2 text-xs text-warn">{nameError}</p>}
      </section>

      <section className="mb-4 rounded-xl2 border border-void-hairline bg-void-card p-4 shadow-soft sm:p-5">
        <div className="mb-3">
          <h2 className="text-base font-bold text-ink">Keamanan</h2>
          <p className="text-xs text-ink-faint">Gunakan password unik minimal 6 karakter.</p>
        </div>
        <form onSubmit={handleChangePassword} className="space-y-2.5">
          <label htmlFor="current-password" className="sr-only">Password saat ini</label>
          <input
            id="current-password"
            type="password"
            placeholder="Password saat ini"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            className="w-full rounded-xl border border-void-hairline bg-void px-3 py-3 text-sm text-ink placeholder:text-ink-faint"
            required
          />
          <label htmlFor="new-password" className="sr-only">Password baru</label>
          <input
            id="new-password"
            type="password"
            placeholder="Password baru (min. 6 karakter)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full rounded-xl border border-void-hairline bg-void px-3 py-3 text-sm text-ink placeholder:text-ink-faint"
            required
            minLength={6}
          />
          {passwordError && <p className="text-xs text-warn">{passwordError}</p>}
          <button
            type="submit"
            disabled={savingPassword}
            className="w-full rounded-xl bg-feed py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            {savingPassword ? "Menyimpan..." : passwordSaved ? "Password Diperbarui ✓" : "Ganti Password"}
          </button>
        </form>
      </section>

      <section className="mb-4 rounded-xl2 border border-void-hairline bg-void-card p-4 shadow-soft sm:p-5">
        <div className="mb-3 flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-soft text-lg" aria-hidden="true">✈️</span>
          <div>
            <h2 className="text-base font-bold text-ink">Notifikasi Telegram</h2>
            <p className="text-xs text-ink-faint">Terima pengingat penting di Telegram.</p>
          </div>
        </div>
        <details className="mb-3">
          <summary className="text-xs cursor-pointer text-feed">Cara dapetin Chat ID</summary>
          <ol className="mt-2 space-y-1 text-xs list-decimal list-inside text-ink-muted">
            <li>Cari bot yang udah dibuatkan (tanya admin/pemilik project kalau belum tau namanya)</li>
            <li>Kirim pesan apa aja ke bot itu, misal "halo"</li>
            <li>
              Buka link{" "}
              <code className="px-1 rounded bg-void">
                https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates
              </code>{" "}
              di browser (ganti TOKEN sesuai punya bot)
            </li>
            <li>Cari angka di bagian <code className="px-1 rounded bg-void">"chat":{"{"}"id": ...{"}"}</code>, itu Chat ID kamu</li>
            <li>Paste angka itu di bawah ini</li>
          </ol>
        </details>
        <form onSubmit={handleSaveTelegram} className="flex flex-col gap-2 min-[380px]:flex-row">
          <label htmlFor="telegram-chat-id" className="sr-only">Chat ID Telegram</label>
          <input
            id="telegram-chat-id"
            type="text"
            placeholder="Chat ID Telegram"
            value={telegramChatId}
            onChange={(e) => setTelegramChatId(e.target.value)}
            className="min-w-0 flex-1 rounded-xl border border-void-hairline bg-void px-3 py-3 text-sm text-ink placeholder:text-ink-faint"
          />
          <button
            type="submit"
            disabled={savingTelegram}
            className="whitespace-nowrap rounded-xl bg-feed px-4 py-3 text-sm font-semibold text-white disabled:opacity-50"
          >
            {savingTelegram ? "..." : telegramSaved ? "Tersimpan ✓" : "Simpan"}
          </button>
        </form>
        {telegramError && <p className="mt-2 text-xs text-warn">{telegramError}</p>}
        {user.telegram_chat_id && (
          <button
            onClick={handleTestTelegram}
            disabled={testing}
            className="mt-3 text-xs font-medium text-feed disabled:opacity-50"
          >
            {testing ? "Mengirim..." : "Kirim Pesan Test"}
          </button>
        )}
        {testResult && <p className="mt-2 text-xs text-ink-muted">{testResult}</p>}
        <p className="text-[11px] text-ink-faint mt-3">
          Reminder harian bakal dikirim kalau: vaksin wajib jatuh tempo, kontrol dokter besok, atau
          belum ada catatan menyusui 6+ jam.
        </p>
      </section>

      <section className="rounded-xl2 border border-void-hairline bg-void-card p-4 shadow-soft sm:p-5">
        <div className="mb-3">
          <h2 className="text-base font-bold text-ink">Anak yang Kamu Akses</h2>
          <p className="text-xs text-ink-faint">Peran menentukan izin melihat dan mengubah catatan.</p>
        </div>
        {loadingRoles ? (
          <p className="text-sm text-ink-faint">Memuat...</p>
        ) : childrenRoles.length === 0 ? (
          <p className="text-sm text-ink-faint">Belum ada anak.</p>
        ) : (
          <div className="space-y-2">
            {childrenRoles.map((c) => (
              <div key={c.id} className="flex items-center justify-between gap-3 rounded-2xl bg-void px-3 py-2.5">
                <div className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-diaper-soft text-sm" aria-hidden="true">👶</span>
                  <p className="truncate text-sm font-semibold text-ink">{c.nickname || c.name}</p>
                </div>
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                    isOwner(c.role) ? "bg-feed/15 text-feed" : "bg-sleep/15 text-sleep"
                  }`}
                >
                  {describeRole(c.role)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
