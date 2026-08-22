import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "../api/client";
import { describeRole, isOwner, ROLE_EDITOR, ROLE_VIEWER } from "../utils/roles";

const INVITE_ROLE_OPTIONS = [
  { value: ROLE_EDITOR, label: "Editor" },
  { value: ROLE_VIEWER, label: "Hanya melihat" },
];

/**
 * Owner-only (App.jsx dan ChildProfileScreen.jsx SAMA-SAMA cuma
 * nampilin pintu masuk ke modal ini buat pemilik — lihat Caregiver
 * Roles & Permissions Phase 1, backend/docs/ROLES_PERMISSIONS.md).
 * Backend TETAP menegakkan ulang SEMUA batasan ini (owner-only invite/
 * ubah peran/cabut) — `myRole === "owner"` di bawah CUMA lapisan kedua
 * (jaga-jaga kalau suatu saat komponen ini dipasang dari tempat lain).
 */
export default function CaregiverModal({ child, currentUserId, onClose }) {
  const [caregivers, setCaregivers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState(null);
  const [inviteRole, setInviteRole] = useState(ROLE_EDITOR);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  // user_id caregiver yang lagi diminta konfirmasi "Yakin?" buat dicabut
  // — 2 langkah, sama pola-nya kayak QueueReviewPanel.jsx, biar nggak
  // ada pencabutan akses yang kejadian gara-gara salah pencet.
  const [confirmingRemove, setConfirmingRemove] = useState(null);
  const [busyUserId, setBusyUserId] = useState(null);
  const panelRef = useRef(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const c = await api.listCaregivers(child.id);
      setCaregivers(c);
    } finally {
      setLoading(false);
    }
  }, [child.id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  const myRole = caregivers.find((c) => c.user_id === currentUserId)?.role;

  const handleInvite = async () => {
    setError("");
    setGenerating(true);
    try {
      const res = await api.createInvite(child.id, inviteRole);
      setInvite(res);
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = () => {
    if (!invite) return;
    navigator.clipboard.writeText(invite.code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleRoleChange = async (userId, newRole) => {
    setError("");
    setBusyUserId(userId);
    try {
      await api.updateCaregiverRole(child.id, userId, newRole);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyUserId(null);
    }
  };

  const handleRemove = async (userId) => {
    setError("");
    setConfirmingRemove(null);
    setBusyUserId(userId);
    try {
      await api.removeCaregiver(child.id, userId);
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyUserId(null);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="caregiver-modal-title"
        tabIndex={-1}
        className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto outline-none"
      >
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <h2 id="caregiver-modal-title" className="font-display text-2xl text-ink mb-1">
          Pengasuh {child.name}
        </h2>
        <p className="text-sm text-ink-muted mb-5">Siapa aja yang bisa catat & lihat data anak ini.</p>

        {error && <p className="text-warn text-sm mb-3">{error}</p>}

        {loading ? (
          <p className="text-ink-faint text-sm">Memuat...</p>
        ) : (
          <div className="space-y-2 mb-5">
            {caregivers.map((c) => {
              const isSelf = c.user_id === currentUserId;
              const isCaregiverOwner = isOwner(c.role);
              const busy = busyUserId === c.user_id;
              return (
                <div
                  key={c.user_id}
                  className="bg-void border border-void-hairline rounded-xl2 px-4 py-3 space-y-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div>
                      <p className="text-sm text-ink">
                        {c.name} {isSelf && <span className="text-ink-faint">(kamu)</span>}
                      </p>
                      <p className="text-xs text-ink-faint">{c.email}</p>
                    </div>
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full font-medium whitespace-nowrap ${
                        isCaregiverOwner ? "bg-feed/15 text-feed" : "bg-sleep/15 text-sleep"
                      }`}
                    >
                      {describeRole(c.role)}
                    </span>
                  </div>

                  {myRole === "owner" && !isSelf && !isCaregiverOwner && (
                    <div className="flex items-center justify-between gap-2 pt-1 border-t border-void-hairline">
                      <div className="flex items-center gap-1.5" role="group" aria-label={`Ubah peran ${c.name}`}>
                        {INVITE_ROLE_OPTIONS.map((opt) => (
                          <button
                            key={opt.value}
                            type="button"
                            disabled={busy}
                            onClick={() => handleRoleChange(c.user_id, opt.value)}
                            aria-pressed={c.role === opt.value}
                            className={`text-[11px] px-2.5 py-1 rounded-full font-medium disabled:opacity-50 ${
                              c.role === opt.value
                                ? "bg-feed/15 text-feed border border-feed/40"
                                : "text-ink-faint border border-void-hairline"
                            }`}
                          >
                            {opt.label}
                          </button>
                        ))}
                      </div>

                      {confirmingRemove === c.user_id ? (
                        <span className="text-[11px] flex items-center gap-2 flex-shrink-0">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleRemove(c.user_id)}
                            className="underline underline-offset-2 text-warn disabled:opacity-50"
                          >
                            Yakin, cabut
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmingRemove(null)}
                            className="underline underline-offset-2 text-ink-faint"
                          >
                            Batal
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => setConfirmingRemove(c.user_id)}
                          className="text-[11px] text-warn flex-shrink-0 disabled:opacity-50"
                        >
                          Cabut
                        </button>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {myRole === "owner" && (
          <div className="border-t border-void-hairline pt-5">
            <p className="text-sm text-ink font-medium mb-2">Undang pengasuh baru</p>
            {!invite ? (
              <>
                <div className="flex items-center gap-2 mb-3" role="group" aria-label="Pilih peran undangan">
                  {INVITE_ROLE_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => setInviteRole(opt.value)}
                      aria-pressed={inviteRole === opt.value}
                      className={`flex-1 text-xs py-2 rounded-lg font-medium border ${
                        inviteRole === opt.value
                          ? "bg-feed/15 text-feed border-feed/40"
                          : "text-ink-muted border-void-hairline"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                <button
                  onClick={handleInvite}
                  disabled={generating}
                  className="w-full py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
                >
                  {generating ? "Membuat kode..." : "Buat Kode Undangan"}
                </button>
              </>
            ) : (
              <div>
                <div className="bg-void border border-feed/30 rounded-xl2 px-4 py-4 text-center mb-2">
                  <p className="text-[11px] text-ink-faint uppercase tracking-wider mb-1">
                    Kode Undangan · {describeRole(invite.role)}
                  </p>
                  <p className="font-display text-2xl text-feed tracking-widest">{invite.code}</p>
                </div>
                <p className="text-[11px] text-ink-faint mb-3">
                  Berlaku 7 hari, sekali pakai. Kirim kode ini ke pasangan/pengasuh — mereka masukkan
                  lewat menu "Sudah punya kode undangan?" pas pertama kali daftar.
                </p>
                <button
                  onClick={handleCopy}
                  className="w-full py-2.5 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
                >
                  {copied ? "Tersalin ✓" : "Salin Kode"}
                </button>
              </div>
            )}
          </div>
        )}

        <button
          onClick={onClose}
          className="w-full py-3 mt-5 rounded-lg border border-void-hairline text-ink-muted text-sm font-medium"
        >
          Tutup
        </button>
      </div>
    </div>
  );
}
