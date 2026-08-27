"""Ringkasan bulanan keluarga; menghitung aktivitas pencatatan, bukan kondisi klinis."""
from calendar import monthrange
from datetime import date,datetime,time

from flask import Blueprint,jsonify,request

from models import (ChildVaccination,DevelopmentGoal,DoctorVisitLog,FamilyDevelopmentCheckIn,
                    FeedingLog,GrowthMeasurement,MemoryJournalEntry,MilestoneLog,SleepLog,DiaperLog)
from utils.access import get_accessible_child
from utils.auth import get_current_user_id

family_monthly_review_bp=Blueprint("family_monthly_review",__name__)


def _bounds(raw):
    try:value=datetime.strptime(raw or "","%Y-%m")
    except ValueError:raise ValueError("Bulan harus berformat YYYY-MM")
    if not 2000<=value.year<=2100:raise ValueError("Tahun harus antara 2000 dan 2100")
    start=date(value.year,value.month,1);end=date(value.year,value.month,monthrange(value.year,value.month)[1])
    if value.month==1:previous=date(value.year-1,12,1)
    else:previous=date(value.year,value.month-1,1)
    previous_end=date(previous.year,previous.month,monthrange(previous.year,previous.month)[1])
    return start,end,previous,previous_end


def _date_count(model,column,child_id,start,end,extra=None):
    query=model.query.filter(model.child_id==child_id,column>=start,column<=end)
    if extra is not None:query=query.filter(extra)
    return query.count()


def _datetime_count(model,column,child_id,start,end):
    return model.query.filter(model.child_id==child_id,column>=datetime.combine(start,time.min),column<=datetime.combine(end,time.max)).count()


def _summary(child_id,start,end):
    goals=DevelopmentGoal.query.filter(DevelopmentGoal.child_id==child_id,DevelopmentGoal.target_date>=start,DevelopmentGoal.target_date<=end)
    return {
      "care_records":{"feeding":_datetime_count(FeedingLog,FeedingLog.timestamp,child_id,start,end),"sleep":_datetime_count(SleepLog,SleepLog.start_time,child_id,start,end),"diaper":_datetime_count(DiaperLog,DiaperLog.timestamp,child_id,start,end)},
      "development":{"memories":_date_count(MemoryJournalEntry,MemoryJournalEntry.occurred_date,child_id,start,end),"milestones":_date_count(MilestoneLog,MilestoneLog.achieved_date,child_id,start,end),"growth_checks":_date_count(GrowthMeasurement,GrowthMeasurement.measured_date,child_id,start,end)},
      "health":{"doctor_visits":_date_count(DoctorVisitLog,DoctorVisitLog.visit_date,child_id,start,end),"vaccinations":_date_count(ChildVaccination,ChildVaccination.given_date,child_id,start,end,ChildVaccination.given.is_(True))},
      "family":{"check_ins":_date_count(FamilyDevelopmentCheckIn,FamilyDevelopmentCheckIn.period_month,child_id,start,end),"discussion_flags":_date_count(FamilyDevelopmentCheckIn,FamilyDevelopmentCheckIn.period_month,child_id,start,end,FamilyDevelopmentCheckIn.discuss_with_professional.is_(True)),"goals_total":goals.count(),"goals_completed":goals.filter(DevelopmentGoal.completed_at.isnot(None)).count()},
    }


def _flatten(summary):
    return {f"{group}.{key}":value for group,items in summary.items() for key,value in items.items()}


@family_monthly_review_bp.route("/children/<int:child_id>/family-monthly-review",methods=["GET"])
def family_monthly_review(child_id):
    user_id=get_current_user_id();child=get_accessible_child(child_id,user_id) if user_id else None
    if not child:return jsonify({"error":"Anak tidak ditemukan"}),404
    try:start,end,previous_start,previous_end=_bounds(request.args.get("month"))
    except ValueError as exc:return jsonify({"error":str(exc)}),400
    current=_summary(child_id,start,end);previous=_summary(child_id,previous_start,previous_end)
    current_flat=_flatten(current);previous_flat=_flatten(previous)
    comparison={key:{"current":value,"previous":previous_flat[key],"difference":value-previous_flat[key]} for key,value in current_flat.items()}
    total_records=sum(current["care_records"].values())+sum(current["development"].values())+sum(current["health"].values())
    return jsonify({"month":start.strftime("%Y-%m"),"period":{"start":start.isoformat(),"end":end.isoformat()},"summary":current,"comparison":comparison,"total_recorded_items":total_records,
      "has_family_review":current["family"]["check_ins"]>0 or current["family"]["goals_total"]>0,
      "disclaimer":"Perbandingan menunjukkan jumlah catatan, bukan perubahan kondisi, kualitas pengasuhan, atau perkembangan kesehatan anak."})
