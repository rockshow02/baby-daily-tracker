import { useRef, useState } from "react";

const REVEAL_WIDTH = 144;

/**
 * Bungkus 1 item riwayat biar bisa digeser ke kiri, nyingkap tombol
 * "Duplikat" dan "Hapus" di belakangnya — pola swipe-action khas app
 * mobile (kayak Gmail/WhatsApp), biar aksi cepat nggak perlu buka modal
 * dulu. Tap biasa (bukan geser) tetap jalan normal ke children-nya
 * (biasanya buka form edit).
 */
export default function SwipeableHistoryItem({ children, onDuplicate, onDelete }) {
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
    const next = Math.max(-REVEAL_WIDTH, Math.min(0, baseXRef.current + delta));
    setTranslateX(next);
  };

  const handleTouchEnd = () => {
    startXRef.current = null;
    // udah geser lebih dari separuh -> snap kebuka penuh, kurang dari itu -> balik nutup
    setTranslateX(translateX < -REVEAL_WIDTH / 2 ? -REVEAL_WIDTH : 0);
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
      <div className="absolute inset-y-0 right-0 flex items-stretch" style={{ width: REVEAL_WIDTH }}>
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