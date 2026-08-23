import { Component } from "react";

/**
 * Error boundary KECIL & LOKAL per-section -- BEDA dari
 * components/ErrorBoundary.jsx (itu buat SELURUH aplikasi, fallback-nya
 * halaman penuh + reload). Renderer 1 section (mis. data section yang
 * bentuknya nggak terduga) yang nge-throw TIDAK BOLEH menjatuhkan
 * seluruh layar konsultasi -- section lain (dan tombol Unduh PDF/Catat
 * Hasil Kunjungan) tetap harus kelihatan & jalan.
 *
 * React Error Boundary WAJIB komponen class (belum ada padanan hook-nya
 * di React 18) -- fallback-nya SENGAJA statis (teks doang, nggak ada
 * logic yang bisa gagal lagi), TIDAK PERNAH nampilin detail
 * error/stack/props section-nya (bisa aja berisi data anak).
 */
export default class SectionErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    if (import.meta.env.DEV) {
      console.error("[SectionErrorBoundary]", this.props.sectionCode, error?.message, info?.componentStack);
    }
  }

  render() {
    if (this.state.hasError) {
      return <p className="text-sm text-warn py-2">Bagian ini tidak dapat ditampilkan.</p>;
    }
    return this.props.children;
  }
}
