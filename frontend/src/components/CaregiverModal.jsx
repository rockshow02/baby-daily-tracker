import { useEffect, useState, useCallback } from "react";
import { api } from "../api/client";

export default function CaregiverModal({ child, currentUserId, onClose }) {
  const [caregivers, setCaregivers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [invite, setInvite] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

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

  const myRole = caregivers.find((c) => c.user_id === currentUserId)?.role;

  const handleInvite = async () => {
    setError("");
    setGenerating(true);
    try {
      const res = await api.createInvite(child.id);
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

  const handleRemove = async (userId) => {
    setError("");
    try {
      await api.removeCaregiver(child.id, userId);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full sm:max-w-sm bg-void-card border-t sm:border border-void-hairline rounded-t-xl2 sm:rounded-xl2 p-6 pb-8 max-h-[85vh] overflow-y-auto">
        <div className="w-10 h-1 bg-void-hairline rounded-full mx-auto mb-5 sm:hidden" />
        <h2 className="font-display text-2xl text-ink mb-1">Pengasuh {child.name}</h2>
        <p className="text-sm text-ink-muted mb-5">Siapa aja yang bisa catat & lihat data anak ini.</p>

        {error && <p className="text-warn text-sm mb-3">{error}</p>}

        {loading ? (
          <p className="text-ink-faint text-sm">Memuat...</p>
        ) : (
          <div className="space-y-2 mb-5">
            {caregivers.map((c) => (
              <div
                key={c.user_id}
                className="flex items-center justify-between bg-void border border-void-hairline rounded-xl2 px-4 py-3"
              >
                <div>
                  <p className="text-sm text-ink">
                    {c.name} {c.user_id === currentUserId && <span className="text-ink-faint">(kamu)</span>}
                  </p>
                  <p className="text-xs text-ink-faint">{c.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${
                      c.role === "owner" ? "bg-feed/15 text-feed" : "bg-sleep/15 text-sleep"
                    }`}
                  >
                    {c.role === "owner" ? "Pemilik" : "Pengasuh"}
                  </span>
                  {myRole === "owner" && c.user_id !== currentUserId && (
                    <button
                      onClick={() => handleRemove(c.user_id)}
                      className="text-[11px] text-warn"
                    >
                      Cabut
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        <div className="border-t border-void-hairline pt-5">
          <p className="text-sm text-ink font-medium mb-2">Undang pengasuh baru</p>
          {!invite ? (
            <button
              onClick={handleInvite}
              disabled={generating}
              className="w-full py-3 rounded-lg bg-feed text-white text-sm font-semibold disabled:opacity-50"
            >
              {generating ? "Membuat kode..." : "Buat Kode Undangan"}
            </button>
          ) : (
            <div>
              <div className="bg-void border border-feed/30 rounded-xl2 px-4 py-4 text-center mb-2">
                <p className="text-[11px] text-ink-faint uppercase tracking-wider mb-1">Kode Undangan</p>
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