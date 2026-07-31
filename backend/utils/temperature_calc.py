"""
Klasifikasi suhu tubuh anak.
Acuan: Kemenkes RI (2019) - Hipotermia <36.5°C, Normal 36.5-37.5°C,
Febris/demam 37.6-40°C, Hipertermia >40°C (pengukuran umum/rektal-oral).

Pengukuran ketiak (aksila) biasanya 0,5-1°C lebih rendah dari suhu inti
tubuh, jadi ambang demamnya sedikit lebih rendah (>37.2°C) sesuai konvensi
klinis dan IDAI.
"""

def classify_temperature(temp_celsius, method="ketiak"):
    if method == "ketiak":
        if temp_celsius < 36.5:
            return "Hipotermia (terlalu dingin)"
        if temp_celsius <= 37.2:
            return "Normal"
        if temp_celsius <= 38.5:
            return "Demam"
        return "Demam tinggi (segera ke dokter)"
    else:
        # dahi, telinga, mulut, dubur - ambang sedikit lebih tinggi
        if temp_celsius < 36.5:
            return "Hipotermia (terlalu dingin)"
        if temp_celsius <= 37.5:
            return "Normal"
        if temp_celsius <= 39:
            return "Demam"
        return "Demam tinggi (segera ke dokter)"