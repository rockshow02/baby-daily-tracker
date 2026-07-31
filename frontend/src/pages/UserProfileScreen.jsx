import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";

export default function UserProfileScreen({ user, onUserUpdated }) {
  const [name, setName] = useState(user.name);
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
      const children = await api.listChildren();
      const withRoles = await Promise.all(
        children.map(async (c) => {
          const caregivers = await api.listCaregivers(c.id);
          const me = caregivers.find((cg) => cg.user_id === user.id);
          return { ...c, role: me?.role || "caregiver" };
        })
      );
      setChildrenRoles(withRoles);
    } finally {
      setLoadingRoles(false);
    }
  }, [user.id]);

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
                    c.role === "owner" ? "bg-feed/15 text-feed" : "bg-sleep/15 text-sleep"
                  }`}
                >
                  {c.role === "owner" ? "Orang Tua / Pemilik" : "Pengasuh"}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}