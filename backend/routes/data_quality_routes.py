"""Pemeriksaan kualitas data read-only, bounded, dan privacy-safe."""
from collections import defaultdict
from datetime import datetime, time, timedelta

from flask import Blueprint, jsonify, request

from models import (ActivityLog, DiaperLog, DoctorVisitLog, FeedingLog,
                    GrowthMeasurement, MedicationLog, MilestoneLog, MoodLog,
                    PumpingLog, SleepLog, TemperatureLog)
from utils.access import get_accessible_child
from utils.auth import get_current_user_id
from utils.timezone_utils import now_wib

data_quality_bp = Blueprint("data_quality", __name__)
CATEGORIES={"duplicate","incomplete","future"}
ALLOWED_DAYS={7,30,90}
MAX_ROWS_PER_SOURCE=300

SOURCES=(
    ("feeding",FeedingLog,FeedingLog.timestamp,"feed_type","daily"),
    ("sleep",SleepLog,SleepLog.start_time,"sleep_type","daily"),
    ("diaper",DiaperLog,DiaperLog.timestamp,"diaper_type","daily"),
    ("pumping",PumpingLog,PumpingLog.timestamp,None,"daily"),
    ("activity",ActivityLog,ActivityLog.timestamp,"activity_type","daily"),
    ("temperature",TemperatureLog,TemperatureLog.timestamp,"method","health"),
    ("medication",MedicationLog,MedicationLog.timestamp,"medication_name","health"),
    ("mood",MoodLog,MoodLog.timestamp,"mood","moments"),
)
DATE_SOURCES=(
    ("growth",GrowthMeasurement,GrowthMeasurement.measured_date,None,"growth"),
    ("doctor",DoctorVisitLog,DoctorVisitLog.visit_date,None,"health"),
    ("milestone",MilestoneLog,MilestoneLog.achieved_date,"milestone_type","moments"),
)
LABELS={"feeding":"menyusui","sleep":"tidur","diaper":"popok","pumping":"perah ASI",
        "activity":"aktivitas","temperature":"suhu","medication":"obat","mood":"mood",
        "growth":"pertumbuhan","doctor":"kunjungan dokter","milestone":"milestone"}


def _issue(category,record_type,key,event_date,title,description,source_ids,screen,severity="review"):
    return {"id":f"{category}-{record_type}-{key}","category":category,"record_type":record_type,
            "date":event_date.isoformat(),"title":title,"description":description,
            "source_ids":source_ids,"screen":screen,"severity":severity}


@data_quality_bp.route("/children/<int:child_id>/data-quality",methods=["GET"])
def data_quality(child_id):
    user_id=get_current_user_id();child=get_accessible_child(child_id,user_id) if user_id else None
    if not child:return jsonify({"error":"Anak tidak ditemukan"}),404
    try:days=int(request.args.get("days","30"))
    except (TypeError,ValueError):return jsonify({"error":"Periode tidak valid"}),400
    if days not in ALLOWED_DAYS:return jsonify({"error":"Periode harus 7, 30, atau 90 hari"}),400
    requested={x.strip() for x in request.args.get("categories","").split(",") if x.strip()}
    if requested-CATEGORIES:return jsonify({"error":"Kategori pemeriksaan tidak valid"}),400
    categories=requested or CATEGORIES;now=now_wib();start_dt=now-timedelta(days=days);start_date=start_dt.date();issues=[]
    loaded={}
    for name,model,column,subtype,screen in SOURCES:
        rows=model.query.filter(model.child_id==child_id,column>=start_dt).order_by(column.desc()).limit(MAX_ROWS_PER_SOURCE).all();loaded[name]=rows
        if "duplicate" in categories:
            groups=defaultdict(list)
            for row in rows:groups[(getattr(row,column.key),getattr(row,subtype) if subtype else None)].append(row.id)
            for (moment,_),ids in groups.items():
                if len(ids)>1:issues.append(_issue("duplicate",name,moment.strftime("%Y%m%d%H%M%S"),moment.date(),f"Kemungkinan catatan {LABELS[name]} ganda",f"{len(ids)} catatan memiliki waktu dan jenis yang sama.",ids,screen))
        if "future" in categories:
            for row in rows:
                moment=getattr(row,column.key)
                if moment>now+timedelta(minutes=5):issues.append(_issue("future",name,row.id,moment.date(),f"Waktu catatan {LABELS[name]} berada di masa depan","Periksa kembali tanggal dan jam catatan ini.",[row.id],screen))
    loaded_dates={}
    for name,model,column,subtype,screen in DATE_SOURCES:
        rows=model.query.filter(model.child_id==child_id,column>=start_date).order_by(column.desc()).limit(MAX_ROWS_PER_SOURCE).all();loaded_dates[name]=rows
        if "duplicate" in categories:
            groups=defaultdict(list)
            for row in rows:groups[(getattr(row,column.key),getattr(row,subtype) if subtype else None)].append(row.id)
            for (day,_),ids in groups.items():
                if len(ids)>1:issues.append(_issue("duplicate",name,day.isoformat(),day,f"Kemungkinan catatan {LABELS[name]} ganda",f"{len(ids)} catatan memiliki tanggal dan jenis yang sama.",ids,screen))
        if "future" in categories:
            for row in rows:
                day=getattr(row,column.key)
                if day>now.date():issues.append(_issue("future",name,row.id,day,f"Tanggal catatan {LABELS[name]} berada di masa depan","Periksa kembali tanggal catatan ini.",[row.id],screen))
    if "incomplete" in categories:
        for row in loaded["feeding"]:
            missing=(row.feed_type=="asi_langsung" and row.duration_minutes is None) or (row.feed_type!="asi_langsung" and row.volume_ml is None)
            if missing:issues.append(_issue("incomplete","feeding",row.id,row.timestamp.date(),"Detail pengukuran menyusui belum diisi","Catatan tetap valid, tetapi durasi atau volumenya belum tersedia.",[row.id],"daily","info"))
        for row in loaded["sleep"]:
            if row.end_time is None and row.start_time<now-timedelta(hours=24):issues.append(_issue("incomplete","sleep",row.id,row.start_time.date(),"Sesi tidur belum ditutup","Waktu mulai sudah lebih dari 24 jam tanpa waktu selesai.",[row.id],"daily"))
        for row in loaded["diaper"]:
            if row.diaper_type in ("pup","keduanya") and row.consistency is None:issues.append(_issue("incomplete","diaper",row.id,row.timestamp.date(),"Detail catatan popok belum lengkap","Konsistensi belum dipilih pada catatan BAB.",[row.id],"daily","info"))
        for row in loaded["medication"]:
            if not row.dosage:issues.append(_issue("incomplete","medication",row.id,row.timestamp.date(),"Detail dosis belum diisi","Nama obat tidak ditampilkan di pusat kualitas data.",[row.id],"health","info"))
        for row in loaded_dates["growth"]:
            if row.weight_kg is None or row.height_cm is None:issues.append(_issue("incomplete","growth",row.id,row.measured_date,"Pengukuran pertumbuhan belum lengkap","Berat atau tinggi belum tersedia pada pengukuran ini.",[row.id],"growth","info"))
    issues.sort(key=lambda x:(x["date"],x["severity"],x["id"]),reverse=True)
    counts={key:sum(1 for issue in issues if issue["category"]==key) for key in sorted(CATEGORIES)}
    return jsonify({"items":issues,"counts":counts,"days":days,"categories":sorted(categories),
        "scanned_sources":len(SOURCES)+len(DATE_SOURCES),"is_clear":len(issues)==0,
        "disclaimer":"Temuan ini adalah pemeriksaan kualitas pencatatan, bukan penilaian kesehatan. Tinjau catatan sumber sebelum mengubah atau menghapus data."})
