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
    <div className="min-h-screen px-6 pt-8 pb-16">
      <h1 className="mb-1 text-3xl font-display text-ink">Profil Saya</h1>
      <p className="mb-6 text-sm text-ink-muted">{user.email}</p>

      <div className="p-4 mb-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
        <p className="mb-3 font-mono text-xs tracking-wider uppercase text-ink-faint">Nama</p>
        <form onSubmit={handleSaveName} className="flex gap-2">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="flex-1 bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink text-sm"
            required
          />
          <button
            type="submit"
            disabled={savingName}
            className="px-4 py-2.5 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50 whitespace-nowrap"
          >
            {savingName ? "..." : nameSaved ? "Tersimpan ✓" : "Simpan"}
          </button>
        </form>
        {nameError && <p className="mt-2 text-xs text-warn">{nameError}</p>}
      </div>

      <div className="p-4 mb-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
        <p className="mb-3 font-mono text-xs tracking-wider uppercase text-ink-faint">Ganti Password</p>
        <form onSubmit={handleChangePassword} className="space-y-2">
          <input
            type="password"
            placeholder="Password saat ini"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink text-sm placeholder:text-ink-faint"
            required
          />
          <input
            type="password"
            placeholder="Password baru (min. 6 karakter)"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            className="w-full bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink text-sm placeholder:text-ink-faint"
            required
            minLength={6}
          />
          {passwordError && <p className="text-xs text-warn">{passwordError}</p>}
          <button
            type="submit"
            disabled={savingPassword}
            className="w-full py-2.5 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
          >
            {savingPassword ? "Menyimpan..." : passwordSaved ? "Password Diperbarui ✓" : "Ganti Password"}
          </button>
        </form>
      </div>

      <div className="p-4 mb-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
        <p className="mb-3 font-mono text-xs tracking-wider uppercase text-ink-faint">Notifikasi Telegram</p>
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
        <form onSubmit={handleSaveTelegram} className="flex gap-2">
          <input
            type="text"
            placeholder="Chat ID Telegram"
            value={telegramChatId}
            onChange={(e) => setTelegramChatId(e.target.value)}
            className="flex-1 bg-void border border-void-hairline rounded-lg px-3 py-2.5 text-ink text-sm placeholder:text-ink-faint"
          />
          <button
            type="submit"
            disabled={savingTelegram}
            className="px-4 py-2.5 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50 whitespace-nowrap"
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
      </div>

      <div className="p-4 border bg-void-card border-void-hairline rounded-xl2 shadow-soft">
        <p className="mb-3 font-mono text-xs tracking-wider uppercase text-ink-faint">Anak yang Kamu Akses</p>
        {loadingRoles ? (
          <p className="text-sm text-ink-faint">Memuat...</p>
        ) : childrenRoles.length === 0 ? (
          <p className="text-sm text-ink-faint">Belum ada anak.</p>
        ) : (
          <div className="space-y-2">
            {childrenRoles.map((c) => (
              <div key={c.id} className="flex items-center justify-between">
                <p className="text-sm text-ink">{c.nickname || c.name}</p>
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
      </div>
    </div>
  );
}