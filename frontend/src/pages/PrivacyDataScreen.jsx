import { useCallback, useEffect, useState } from "react";
import { api, getCurrentUserId } from "../api/client";
import { getQueueForUser, QUEUE_STATUS } from "../utils/offlineQueue";

function safeFilename(value) {
  return (value || "anak").replace(/[^a-z0-9_-]+/gi, "-").replace(/^-+|-+$/g, "") || "anak";
}

function ConfirmPanel({ action, onCancel, onSuccess }) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await action.run({ password, confirmation });
      await onSuccess(action);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-end sm:items-center sm:justify-center">
      <button type="button" aria-label="Tutup konfirmasi" className="absolute inset-0 bg-black/60" onClick={onCancel} />
      <form onSubmit={submit} className="relative w-full sm:max-w-md rounded-t-xl2 sm:rounded-xl2 border border-void-hairline bg-void-card p-5 pb-7">
        <h2 className="font-display text-2xl text-ink">{action.title}</h2>
        <p className="mt-2 text-sm text-ink-muted">{action.description}</p>
        <p className="mt-4 text-xs text-ink-muted">
          Ketik <strong className="text-ink">{action.confirmationText}</strong> untuk melanjutkan.
        </p>
        <input
          aria-label="Teks konfirmasi"
          value={confirmation}
          onChange={(e) => setConfirmation(e.target.value)}
          className="mt-2 w-full rounded-lg border border-void-hairline bg-void px-3 py-2.5 text-sm text-ink"
          autoComplete="off"
          required
        />
        <input
          aria-label="Password saat ini"
          type="password"
          placeholder="Password saat ini"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mt-2 w-full rounded-lg border border-void-hairline bg-void px-3 py-2.5 text-sm text-ink"
          autoComplete="current-password"
          required
        />
        {error && <p className="mt-2 text-xs text-warn">{error}</p>}
        <div className="mt-4 grid grid-cols-2 gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-void-hairline py-2.5 text-sm text-ink-muted">
            Batal
          </button>
          <button
            type="submit"
            disabled={busy || confirmation !== action.confirmationText}
            className="rounded-lg bg-warn py-2.5 text-sm font-semibold text-white disabled:opacity-40"
          >
            {busy ? "Memproses..." : action.buttonLabel}
          </button>
        </div>
      </form>
    </div>
  );
}

export default function PrivacyDataScreen({ onAccessChanged, onAccountDeleted, onClose }) {
  const [overview, setOverview] = useState(null);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [action, setAction] = useState(null);
  const [pending, setPending] = useState([]);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setStatus("loading");
    setError("");
    try {
      const [data, queue] = await Promise.all([
        api.privacyOverview(),
        getQueueForUser(getCurrentUserId()).catch(() => []),
      ]);
      setOverview(data);
      setPending(queue.filter((item) => item.status !== QUEUE_STATUS.NEEDS_REVIEW));
      setStatus("ready");
    } catch (err) {
      setError(err.message);
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pendingForChild = (childId) => pending.some((item) => new RegExp(`/children/${childId}(?:/|$)`).test(item.url));

  const downloadBackup = async (entry) => {
    setNotice("");
    try {
      await api.downloadAuthenticated(
        api.exportJsonUrl(entry.child.id),
        `backup-${safeFilename(entry.child.nickname || entry.child.name)}.json`,
      );
      setNotice("Backup berhasil diunduh. Simpan file tersebut di tempat yang aman.");
    } catch (err) {
      setNotice(err.message);
    }
  };

  const openChildAction = (entry, type) => {
    if (pendingForChild(entry.child.id)) {
      setNotice("Masih ada catatan anak ini yang belum tersinkron. Selesaikan sinkronisasi sebelum mencabut atau menghapus akses.");
      return;
    }
    const deleting = type === "delete";
    setAction({
      kind: type,
      title: deleting ? `Hapus semua data ${entry.child.name}?` : `Keluar dari akses ${entry.child.name}?`,
      description: deleting
        ? `Tindakan permanen ini menghapus ${entry.total_records} catatan, akses ${entry.caregiver_count} caregiver, profil, dan foto anak.`
        : "Anda tidak akan bisa melihat atau mencatat data anak ini lagi. Data anak tetap aman bersama pemiliknya.",
      confirmationText: entry.child.name,
      buttonLabel: deleting ? "Hapus permanen" : "Keluar dari akses",
      run: (payload) => deleting ? api.deleteChildData(entry.child.id, payload) : api.leaveChildAccess(entry.child.id, payload),
    });
  };

  const openAccountDeletion = () => {
    if (pending.length) {
      setNotice("Masih ada catatan offline yang belum tersinkron. Selesaikan dahulu sebelum menghapus akun.");
      return;
    }
    setAction({
      kind: "account",
      title: "Hapus akun saya?",
      description: "Identitas pribadi dan seluruh akses akan dihapus, semua token dinonaktifkan, dan Anda langsung keluar. ID anonim hanya dipertahankan agar riwayat bersama caregiver lain tetap utuh.",
      confirmationText: "HAPUS AKUN",
      buttonLabel: "Hapus akun",
      run: api.deleteAccount,
    });
  };

  const actionSucceeded = async (completedAction) => {
    setAction(null);
    if (completedAction.kind === "account") {
      await onAccountDeleted();
      return;
    }
    setNotice("Perubahan akses berhasil diproses.");
    await onAccessChanged();
  };

  if (status === "loading") return <p className="px-6 py-12 text-center text-sm text-ink-faint">Memuat pusat privasi...</p>;
  if (status === "error") return (
    <div className="px-6 py-12 text-center">
      <p className="text-sm text-warn">{error}</p>
      <button type="button" onClick={load} className="mt-3 text-sm font-semibold text-feed">Coba lagi</button>
    </div>
  );

  return (
    <div className="min-h-screen px-6 pb-20 pt-8">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-3xl text-ink">Privasi & Data</h1>
        {onClose && (
          <button type="button" onClick={onClose} className="text-xs font-medium text-feed">Kembali</button>
        )}
      </div>
      <p className="mt-1 text-sm text-ink-muted">Lihat apa yang tersimpan, buat salinan, atau kelola akses secara aman.</p>

      {notice && <p className="mt-4 rounded-lg border border-feed/30 bg-feed/10 px-3 py-2 text-xs text-ink">{notice}</p>}
      {pending.length > 0 && (
        <p className="mt-4 rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-ink">
          Ada {pending.length} catatan offline menunggu sinkronisasi. Aksi destruktif terkait data tersebut sementara diblokir.
        </p>
      )}

      <div className="mt-6 space-y-4">
        {overview.children.map((entry) => (
          <section key={entry.child.id} className="rounded-xl2 border border-void-hairline bg-void-card p-4 shadow-soft">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-display text-xl text-ink">{entry.child.nickname || entry.child.name}</h2>
                <p className="text-xs text-ink-faint">{entry.child.role === "owner" ? "Pemilik" : entry.child.role === "editor" ? "Editor" : "Viewer"}</p>
              </div>
              <span className="rounded-full bg-feed/10 px-2 py-1 text-xs text-feed">{entry.total_records} catatan</span>
            </div>
            <details className="mt-3">
              <summary className="cursor-pointer text-xs font-medium text-feed">Lihat inventaris data</summary>
              <div className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2">
                {entry.record_groups.filter((group) => group.count > 0).map((group) => (
                  <div key={group.key} className="flex justify-between gap-2 text-xs">
                    <span className="text-ink-muted">{group.label}</span><span className="text-ink">{group.count}</span>
                  </div>
                ))}
                {entry.total_records === 0 && <p className="col-span-2 text-xs text-ink-faint">Belum ada catatan aktivitas.</p>}
              </div>
              <p className="mt-3 text-[11px] text-ink-faint">{entry.caregiver_count} caregiver · {entry.has_photo ? "Foto tersimpan" : "Tanpa foto"}</p>
            </details>
            <button type="button" onClick={() => downloadBackup(entry)} className="mt-4 w-full rounded-lg border border-feed py-2.5 text-sm font-semibold text-feed">
              Unduh backup JSON
            </button>
            {entry.capabilities.can_delete_child && (
              <button type="button" onClick={() => openChildAction(entry, "delete")} className="mt-2 w-full py-2 text-xs font-medium text-warn">
                Hapus semua data anak
              </button>
            )}
            {entry.capabilities.can_leave_child && (
              <button type="button" onClick={() => openChildAction(entry, "leave")} className="mt-2 w-full py-2 text-xs font-medium text-warn">
                Keluar dari akses anak
              </button>
            )}
          </section>
        ))}
      </div>

      <section className="mt-6 rounded-xl2 border border-warn/30 bg-void-card p-4">
        <h2 className="font-display text-xl text-ink">Hapus akun</h2>
        <p className="mt-2 text-xs leading-relaxed text-ink-muted">
          Identitas pribadi dihapus dan akun dinonaktifkan permanen. Catatan yang pernah Anda buat bersama keluarga lain tetap ada dengan nama “Akun dihapus”.
        </p>
        {overview.account.owned_children > 0 ? (
          <p className="mt-3 text-xs text-warn">Anda masih memiliki {overview.account.owned_children} profil anak. Hapus profil tersebut terlebih dahulu.</p>
        ) : (
          <button type="button" onClick={openAccountDeletion} className="mt-4 w-full rounded-lg border border-warn py-2.5 text-sm font-semibold text-warn">
            Hapus akun saya
          </button>
        )}
      </section>

      {action && <ConfirmPanel action={action} onCancel={() => setAction(null)} onSuccess={actionSucceeded} />}
    </div>
  );
}
