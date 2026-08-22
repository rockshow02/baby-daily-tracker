import { useRef, useState } from "react";
import { describeQueueItem, REVIEW_REASON } from "../utils/offlineQueue";
import RequestIdDetail from "./RequestIdDetail";
import {
  FIELD_TYPE,
  getEditableSchema,
  hasUnsupportedField,
  validateEditedBody,
  toDatetimeLocalValue,
  fromDatetimeLocalValue,
} from "../utils/queueFieldSchemas";

function formatTimestamp(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("id-ID");
  } catch (_) {
    return "";
  }
}

function safeParseBody(item) {
  try {
    return item.body ? JSON.parse(item.body) : {};
  } catch (_) {
    return {};
  }
}

function FieldControl({ field, value, onChange }) {
  if (field.type === FIELD_TYPE.SELECT) {
    return (
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="flex-1 max-w-[140px] bg-void-bg border border-void-hairline rounded px-2 py-1 text-ink"
      >
        <option value="" disabled>
          Pilih...
        </option>
        {field.options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === FIELD_TYPE.DATETIME) {
    return (
      <input
        type="datetime-local"
        value={toDatetimeLocalValue(value)}
        onChange={(e) => onChange(fromDatetimeLocalValue(e.target.value))}
        className="flex-1 max-w-[170px] bg-void-bg border border-void-hairline rounded px-2 py-1 text-ink"
      />
    );
  }
  return (
    <input
      type={field.type === FIELD_TYPE.NUMBER ? "number" : "text"}
      value={value ?? ""}
      onChange={(e) => {
        const raw = e.target.value;
        onChange(field.type === FIELD_TYPE.NUMBER ? (raw === "" ? "" : Number(raw)) : raw);
      }}
      className="flex-1 max-w-[140px] bg-void-bg border border-void-hairline rounded px-2 py-1 text-ink text-right"
    />
  );
}

function EditableFields({ schema, editedBody, onChange }) {
  return (
    <div className="space-y-1.5 mt-2">
      {schema.map((field) => (
        <label key={field.key} className="flex items-center justify-between gap-2 text-[11px]">
          <span className="text-ink-faint">
            {field.label}
            {field.required ? " *" : ""}
          </span>
          <FieldControl
            field={field}
            value={editedBody[field.key]}
            onChange={(next) => onChange({ ...editedBody, [field.key]: next })}
          />
        </label>
      ))}
    </div>
  );
}

function SummaryChips({ summary }) {
  const entries = Object.entries(summary);
  if (entries.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 text-[11px] text-ink-muted">
      {entries.map(([k, v]) => (
        <span key={k} className="bg-void-bg rounded px-1.5 py-0.5">
          {k}: {String(v)}
        </span>
      ))}
    </div>
  );
}

// `onConfirmingChange` opsional (dipanggil dengan true/false) — dipakai
// SyncCenter buat tau kapan ADA konfirmasi buang yang lagi kebuka di mana
// pun di panel ini, biar Escape/klik-luar nggak nutup seluruh Sync
// Center sambil user lagi di tengah konfirmasi 2-langkah ini (lihat
// components/SyncCenter.jsx). Opsional & default no-op — pemakaian lama
// (OfflineStatusBanner) yang nggak ngasih prop ini tetap jalan sama
// persis kayak sebelumnya.
function DiscardControl({ onConfirm, onConfirmingChange }) {
  const [confirming, setConfirmingRaw] = useState(false);
  const setConfirming = (value) => {
    setConfirmingRaw(value);
    onConfirmingChange?.(value);
  };
  if (!confirming) {
    return (
      <button onClick={() => setConfirming(true)} className="underline underline-offset-2 text-warn">
        Buang
      </button>
    );
  }
  return (
    <span className="flex items-center gap-2">
      <span className="text-ink-faint">Yakin?</span>
      <button
        onClick={() => {
          setConfirming(false);
          onConfirm();
        }}
        className="underline underline-offset-2 text-warn"
      >
        Buang
      </button>
      <button onClick={() => setConfirming(false)} className="underline underline-offset-2 text-ink-faint">
        Batal
      </button>
    </span>
  );
}

function NeedsReviewCard({ item, onDiscard, onRetry, onConfirmingChange }) {
  const { typeLabel, summary } = describeQueueItem(item);
  const parsedBody = safeParseBody(item);
  const schema = getEditableSchema(typeLabel);
  const [editing, setEditing] = useState(false);
  const [editedBody, setEditedBody] = useState(summary);
  const [localError, setLocalError] = useState(null);

  const isAccessIssue = item.reviewReason === REVIEW_REASON.ACCESS_REVOKED;
  const isConflict = item.reviewReason === REVIEW_REASON.CONFLICT;
  // 403 (akses dicabut) dan 409 (konflik fingerprint) SAMA-SAMA nggak bisa
  // "diperbaiki" lewat edit data — retry buta cuma bakal nolak lagi.
  const cannotBeFixedByEditing = isAccessIssue || isConflict;
  // Field yang errornya nyangkut nggak ada di schema aman (mis. illness_id)
  // — jangan nawarin edit yang nggak bakal nolong.
  const needsManualRecreate = !cannotBeFixedByEditing && (schema.length === 0 || hasUnsupportedField(typeLabel, parsedBody));

  // Caregiver Roles & Permissions Phase 1 — backend balikin 403 yang
  // SAMA baik buat "akses dicabut total" MAUPUN "peran diturunkan jadi
  // Hanya melihat" (lihat backend/docs/ROLES_PERMISSIONS.md), jadi pesan
  // di sini SENGAJA nyebut dua-duanya sebagai kemungkinan, bukan
  // nebak salah satu.
  const reasonLabel = isAccessIssue
    ? "Akses atau peranmu untuk anak ini mungkin sudah berubah (dicabut, atau diubah jadi Hanya melihat) — catatan ini tidak bisa disimpan otomatis."
    : isConflict
    ? "Request ini sudah pernah diproses server dengan data yang berbeda — catatan ini TIDAK disimpan otomatis lagi supaya nggak nyimpen data yang salah."
    : item.lastError || "Server menolak catatan ini.";

  const handleRetry = () => {
    const validationError = validateEditedBody(typeLabel, editedBody);
    if (validationError) {
      setLocalError(validationError);
      return;
    }
    setLocalError(null);
    onRetry(item.id, JSON.stringify({ ...parsedBody, ...editedBody }));
    setEditing(false);
  };

  return (
    <div className="bg-void-card/60 rounded-lg px-3 py-2 space-y-1.5">
      <div>
        <p className="font-medium text-ink">{typeLabel}</p>
        <p className="text-ink-faint text-[11px]">{formatTimestamp(item.queuedAt)}</p>
      </div>
      <p className="text-warn text-[11px]">{reasonLabel}</p>

      {needsManualRecreate && (
        <p className="text-ink-faint text-[11px]">
          Catatan ini punya data yang nggak bisa diedit dengan aman lewat sini. Buang catatan ini,
          lalu catat ulang manual lewat form biasa.
        </p>
      )}

      {editing ? (
        <>
          <EditableFields schema={schema} editedBody={editedBody} onChange={setEditedBody} />
          {localError && <p className="text-warn text-[11px]">{localError}</p>}
        </>
      ) : (
        <SummaryChips summary={summary} />
      )}

      {/* Item ini SUDAH punya owner yang jelas (needs_review, BUKAN
          legacy/unclaimed) — aman nampilin request ID buat troubleshooting.
          Item legacy (LegacyCard di bawah) SENGAJA nggak pernah dikasih
          komponen ini sama sekali, kepemilikannya belum diverifikasi. */}
      <RequestIdDetail requestId={item.lastRequestId} />

      <div className="flex items-center gap-3 pt-1">
        {!cannotBeFixedByEditing && !needsManualRecreate && !editing && (
          <button onClick={() => setEditing(true)} className="underline underline-offset-2 text-feed">
            Edit
          </button>
        )}
        {editing && (
          <>
            <button onClick={handleRetry} className="underline underline-offset-2 text-feed">
              Coba lagi
            </button>
            <button
              onClick={() => {
                setEditing(false);
                setLocalError(null);
              }}
              className="underline underline-offset-2 text-ink-faint"
            >
              Batal
            </button>
          </>
        )}
        {!editing && (
          <DiscardControl onConfirm={() => onDiscard(item.id)} onConfirmingChange={onConfirmingChange} />
        )}
      </div>
    </div>
  );
}

function LegacyCard({ item, onDiscard, onClaim, onConfirmingChange }) {
  // SENGAJA cuma ambil typeLabel — childId/summary (data kesehatan bayi)
  // TIDAK ditampilin sebelum kepemilikan diverifikasi backend. Endpoint
  // mentah dan body request juga nggak pernah dirender di sini.
  const { typeLabel } = describeQueueItem(item);
  const [claiming, setClaiming] = useState(false);
  const [claimError, setClaimError] = useState(null);

  const handleClaim = async () => {
    setClaiming(true);
    setClaimError(null);
    const result = await onClaim(item.id);
    setClaiming(false);
    if (!result.claimed) setClaimError(result.reason);
  };

  return (
    <div className="bg-void-card/60 rounded-lg px-3 py-2 space-y-1.5">
      <div>
        <p className="font-medium text-ink">{typeLabel}</p>
        <p className="text-ink-faint text-[11px]">{formatTimestamp(item.queuedAt)}</p>
      </div>
      <p className="text-warn text-[11px]">
        Kepemilikan akun belum bisa dipastikan — catatan ini dari sebelum pembaruan keamanan
        antrian offline. Detailnya disembunyikan sampai kamu klaim dan diverifikasi sebagai
        pemiliknya. Klaim kalau ini catatanmu, atau buang kalau bukan.
      </p>
      {claimError && <p className="text-warn text-[11px]">{claimError}</p>}
      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={handleClaim}
          disabled={claiming}
          className="underline underline-offset-2 text-feed disabled:opacity-50"
        >
          {claiming ? "Memeriksa..." : "Klaim akun ini"}
        </button>
        <DiscardControl onConfirm={() => onDiscard(item.id)} onConfirmingChange={onConfirmingChange} />
      </div>
    </div>
  );
}

export default function QueueReviewPanel({
  needsReviewItems,
  legacyItems,
  discardItem,
  claimLegacyItem,
  retryWithEdits,
  onAnyConfirmingChange,
}) {
  // Melacak SEMUA card yang lagi nampilin konfirmasi "Yakin?" (bisa lebih
  // dari 1 kalau user buka konfirmasi di beberapa card sebelum mutusin) —
  // aggregatnya (ada minimal 1 yang confirming atau nggak sama sekali)
  // yang diteruskan ke pemanggil, BUKAN detail per-item.
  const confirmingIdsRef = useRef(new Set());
  const handleConfirmingChange = (itemId) => (isConfirming) => {
    if (isConfirming) confirmingIdsRef.current.add(itemId);
    else confirmingIdsRef.current.delete(itemId);
    onAnyConfirmingChange?.(confirmingIdsRef.current.size > 0);
  };

  if (needsReviewItems.length === 0 && legacyItems.length === 0) return null;

  return (
    <div className="px-4 pb-3 space-y-2 text-xs">
      {legacyItems.map((item) => (
        <LegacyCard
          key={item.id}
          item={item}
          onDiscard={discardItem}
          onClaim={claimLegacyItem}
          onConfirmingChange={handleConfirmingChange(item.id)}
        />
      ))}
      {needsReviewItems.map((item) => (
        <NeedsReviewCard
          key={item.id}
          item={item}
          onDiscard={discardItem}
          onRetry={retryWithEdits}
          onConfirmingChange={handleConfirmingChange(item.id)}
        />
      ))}
    </div>
  );
}
