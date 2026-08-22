import { useRef, useState } from "react";

const BUTTON_WIDTH = 72;

/**
 * Bungkus 1 item riwayat biar bisa digeser ke kiri, nyingkap tombol
 * "Duplikat" dan "Hapus" di belakangnya — pola swipe-action khas app
 * mobile (kayak Gmail/WhatsApp), biar aksi cepat nggak perlu buka modal
 * dulu. Tap biasa (bukan geser) tetap jalan normal ke children-nya
 * (biasanya buka form edit).
 *
 * `canDelete=false` (Caregiver Roles & Permissions Phase 1 — editor
 * ngelihat record buatan caregiver lain) nyembunyiin tombol "Hapus"
 * doang, "Duplikat" TETAP ada (bikin record BARU, izinnya beda dari
 * hapus record ORANG LAIN) — backend TETAP nolak kalau somehow ke-panggil
 * juga, ini CUMA nyembunyiin kontrol yang emang bakal ditolak.
 */
export default function SwipeableHistoryItem({ children, onDuplicate, onDelete, canDelete = true }) {
  const revealWidth = canDelete ? BUTTON_WIDTH * 2 : BUTTON_WIDTH;
  const [translateX, setTranslateX] = useState(0);
  const startXRef = useRef(null);
  const baseXRef = useRef(0);
  const draggedRef = useRef(false);

  const handleTouchStart = (e) => {
    startXRef.current = e.touches[0].clientX;
    baseXRef.current = translateX;
    draggedRef.current = false;
  };

  const handleTouchMove = (e) => {
    if (startXRef.current === null) return;
    const delta = e.touches[0].clientX - startXRef.current;
    if (Math.abs(delta) > 8) draggedRef.current = true;
    const next = Math.max(-revealWidth, Math.min(0, baseXRef.current + delta));
    setTranslateX(next);
  };

  const handleTouchEnd = () => {
    startXRef.current = null;
    // udah geser lebih dari separuh -> snap kebuka penuh, kurang dari itu -> balik nutup
    setTranslateX(translateX < -revealWidth / 2 ? -revealWidth : 0);
  };

  const closeReveal = () => setTranslateX(0);

  const handleClickCapture = (e) => {
    // abis geser beneran, ATAU lagi kebuka -> tahan klik biar nggak nembus
    // ke item (yang biasanya buka form edit); klik pertama pas kebuka
    // cuma buat nutup reveal-nya lagi
    if (draggedRef.current || translateX !== 0) {
      e.stopPropagation();
      e.preventDefault();
      if (translateX !== 0) closeReveal();
      draggedRef.current = false;
    }
  };

  return (
    <div className="relative overflow-hidden rounded-xl2">
      <div className="absolute inset-y-0 right-0 flex items-stretch" style={{ width: revealWidth }}>
        <button
          type="button"
          onClick={() => {
            onDuplicate();
            closeReveal();
          }}
          className="w-[72px] bg-feed text-white text-[11px] font-medium flex flex-col items-center justify-center gap-0.5"
        >
          <span className="text-base">📋</span>
          Duplikat
        </button>
        {canDelete && (
          <button
            type="button"
            onClick={() => {
              onDelete();
              closeReveal();
            }}
            className="w-[72px] bg-warn text-white text-[11px] font-medium flex flex-col items-center justify-center gap-0.5"
          >
            <span className="text-base">🗑️</span>
            Hapus
          </button>
        )}
      </div>

      <div
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
        onClickCapture={handleClickCapture}
        style={{
          transform: `translateX(${translateX}px)`,
          transition: startXRef.current !== null ? "none" : "transform 0.2s ease-out",
        }}
        className="relative bg-void"
      >
        {children}
      </div>
    </div>
  );
}