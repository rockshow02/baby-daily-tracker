"""
Perhitungan status pertumbuhan berdasarkan WHO Child Growth Standards.
Menggunakan metode LMS (Lambda-Mu-Sigma) resmi WHO untuk menghitung z-score,
lalu dikonversi ke persentil.
"""
import math

from models import GrowthReference


def get_reference(measurement_type, gender, age_months):
    """
    Ambil parameter L,M,S buat usia tertentu. Kalau usianya persis ada di
    tabel, pakai langsung. Kalau di antara dua bulan (usia dalam hari
    dikonversi ke bulan pecahan), interpolasi linear biar lebih presisi.
    """
    lower_month = int(math.floor(age_months))
    upper_month = int(math.ceil(age_months))
    lower_month = max(0, min(lower_month, 60))
    upper_month = max(0, min(upper_month, 60))

    ref_lower = GrowthReference.query.filter_by(
        measurement_type=measurement_type, gender=gender, age_months=lower_month
    ).first()

    if lower_month == upper_month or not ref_lower:
        return ref_lower

    ref_upper = GrowthReference.query.filter_by(
        measurement_type=measurement_type, gender=gender, age_months=upper_month
    ).first()

    if not ref_upper:
        return ref_lower

    frac = age_months - lower_month
    return {
        "L": ref_lower.L + (ref_upper.L - ref_lower.L) * frac,
        "M": ref_lower.M + (ref_upper.M - ref_lower.M) * frac,
        "S": ref_lower.S + (ref_upper.S - ref_lower.S) * frac,
    }


def _get_val(ref, key):
    return ref[key] if isinstance(ref, dict) else getattr(ref, key)


def compute_zscore(value, ref):
    """Rumus LMS resmi WHO: z = (((value/M)^L) - 1) / (L * S), atau ln kalau L=0."""
    L = _get_val(ref, "L")
    M = _get_val(ref, "M")
    S = _get_val(ref, "S")

    if L == 0:
        return math.log(value / M) / S
    return (((value / M) ** L) - 1) / (L * S)


def zscore_to_percentile(z):
    """Konversi z-score ke persentil pakai fungsi distribusi normal kumulatif."""
    percentile = 0.5 * (1 + math.erf(z / math.sqrt(2))) * 100
    return round(percentile, 1)


def value_at_zscore(ref, z):
    """Kebalikan dari compute_zscore: dari z-score tertentu, cari nilai ukurannya."""
    L = _get_val(ref, "L")
    M = _get_val(ref, "M")
    S = _get_val(ref, "S")

    if L == 0:
        return M * math.exp(S * z)
    return M * ((1 + L * S * z) ** (1 / L))


STATUS_LABELS = {
    "weight": {
        (-999, -3): "Gizi buruk (sangat kurang)",
        (-3, -2): "Gizi kurang",
        (-2, 2): "Gizi baik (normal)",
        (2, 999): "Risiko gizi lebih",
    },
    "height": {
        (-999, -3): "Sangat pendek (severely stunted)",
        (-3, -2): "Pendek (stunted)",
        (-2, 2): "Normal",
        (2, 999): "Tinggi",
    },
    "head_circumference": {
        (-999, -2): "Di bawah normal (perlu dipantau)",
        (-2, 2): "Normal",
        (2, 999): "Di atas normal (perlu dipantau)",
    },
}


def classify_status(measurement_type, z):
    labels = STATUS_LABELS.get(measurement_type, {})
    for (low, high), label in labels.items():
        if low <= z < high:
            return label
    return None


def evaluate_measurement(measurement_type, value, gender, age_months):
    """Return dict {z_score, percentile, status} atau None kalau data acuan nggak ada."""
    ref = get_reference(measurement_type, gender, age_months)
    if not ref or value is None:
        return None
    z = compute_zscore(value, ref)
    return {
        "z_score": round(z, 2),
        "percentile": zscore_to_percentile(z),
        "status": classify_status(measurement_type, z),
    }