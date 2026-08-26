import { Component } from "react";

/**
 * ID error yang aman ditampilkan ke user (buat disebutin kalau lapor
 * masalah) — random doang, BUKAN diturunkan dari isi error/stack/props,
 * jadi nggak mungkin bocorin apa pun soal state aplikasi.
 */
function generateSafeErrorId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Error Boundary di sekitar aplikasi utama — nangkep error render/lifecycle
 * di komponen anak (BUKAN error di dalam handler event, promise gagal di
 * background, kegagalan API, atau service worker — itu semua tetap lewat
 * jalur penanganannya masing-masing yang udah ada, React Error Boundary
 * emang nggak pernah nangkep itu).
 *
 * SENGAJA nggak pernah nyentuh localStorage/IndexedDB (token, cache sesi,
 * antrian offline) — komponen React yang crash BUKAN alasan buat nge-logout
 * user atau ngilangin catatan yang lagi nunggu disinkron. Fallback-nya
 * sendiri dibikin sesederhana mungkin (teks + 2 tombol, nggak ada logic
 * yang bisa gagal) biar nggak ada risiko error di fallback-nya sendiri
 * bikin loop.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, errorId: null, resetKey: 0 };
  }

  static getDerivedStateFromError() {
    return { hasError: true, errorId: generateSafeErrorId() };
  }

  componentDidCatch(error, info) {
    // Cuma di dev, dan cuma metadata yang aman (pesan error + component
    // stack React — struktur nama komponen, BUKAN isi props/state) — nggak
    // pernah ke production console.
    if (import.meta.env.DEV) {
      console.error("[ErrorBoundary]", this.state.errorId, error?.message, info?.componentStack);
    }
  }

  handleRetry = () => {
    // resetKey berubah -> key di wrapper children berubah -> React BENERAN
    // remount subtree-nya (bukan cuma nampilin lagi instance lama yang
    // sama, yang state internalnya mungkin udah korup gara-gara error tadi)
    this.setState((prev) => ({ hasError: false, errorId: null, resetKey: prev.resetKey + 1 }));
  };

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex flex-col items-center justify-center px-6 text-center bg-void">
          <p className="font-mono text-xs text-ink-faint tracking-[0.2em] uppercase mb-3">Baby Daily Tracker</p>
          <h1 className="font-display text-2xl text-ink mb-2">Ups, ada yang nggak beres.</h1>
          <p className="text-sm text-ink-muted mb-1 max-w-xs">
            Terjadi kesalahan yang nggak terduga di aplikasi. Catatan yang udah tersimpan tetap aman.
          </p>
          <p className="text-xs text-ink-faint font-mono mb-6" data-testid="error-boundary-id">
            Kode error: {this.state.errorId}
          </p>
          <div className="flex gap-3">
            <button
              type="button"
              onClick={this.handleRetry}
              className="px-4 py-2.5 rounded-xl2 bg-feed text-white text-sm font-medium"
            >
              Coba lagi
            </button>
            <button
              type="button"
              onClick={this.handleReload}
              className="px-4 py-2.5 rounded-xl2 border border-void-hairline text-ink-muted text-sm font-medium"
            >
              Muat ulang aplikasi
            </button>
          </div>
        </div>
      );
    }

    return <div key={this.state.resetKey}>{this.props.children}</div>;
  }
}
