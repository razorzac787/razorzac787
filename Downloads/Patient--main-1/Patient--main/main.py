
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Integer, Boolean, ForeignKey, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

DATABASE_URL = "sqlite:///./clinical_app.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Patient(Base):
    __tablename__ = "patients"
    patient_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    age = Column(Integer, nullable=True)
    sex = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    language = Column(String, default="en")
    abha_id = Column(String, unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    consents = relationship("Consent", back_populates="patient")
    timeline_events = relationship("MedicalTimeline", back_populates="patient")

class Consent(Base):
    __tablename__ = "consents"
    consent_id = Column(String, primary_key=True)
    patient_id = Column(String, ForeignKey("patients.patient_id"))
    purpose = Column(String, default="CLINICAL_CARE")
    status = Column(String, default="GRANTED")
    granted_at = Column(DateTime, default=datetime.utcnow)
    patient = relationship("Patient", back_populates="consents")

class MedicalTimeline(Base):
    __tablename__ = "medical_timeline"
    event_id = Column(String, primary_key=True)
    patient_id = Column(String, ForeignKey("patients.patient_id"))
    event_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    summary_data = Column(JSON, nullable=True)
    file_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    patient = relationship("Patient", back_populates="timeline_events")

Base.metadata.create_all(bind=engine)

class ABHARequestOTP(BaseModel):
    abha_id: str = Field(..., example="patient@abdm")

class ABHAVerifyOTP(BaseModel):
    abha_id: str = Field(..., example="patient@abdm")
    otp: str = Field(..., example="123456")

class TimelineEventCreate(BaseModel):
    event_id: str
    patient_id: str
    event_type: str
    title: str
    summary_data: Optional[Dict[str, Any]] = None
    file_url: Optional[str] = None

class PatientIntakeSubmit(BaseModel):
    patient_id: str
    ayush_profile: Dict[str, Any]
    transcript: str
    document_ids: Optional[List[str]] = None

class AISummaryPayload(BaseModel):
    patient_id: str
    chief_complaint: str
    hpi: str
    past_meds: Optional[str] = None
    lab_anomalies: Optional[str] = None
    is_emergency: bool = False
    emergency_reason: Optional[str] = None

app = FastAPI(title="ABDM Clinical Engine", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
def seed_data():
    db = SessionLocal()
    if not db.query(Patient).filter(Patient.patient_id == "P-101").first():
        mock_patient = Patient(
            patient_id="P-101",
            name="Rahul Sharma",
            age=34,
            sex="Male",
            phone="9876543210",
            language="hi",
            abha_id="rahul@abdm"
        )
        db.add(mock_patient)
        db.commit()
    db.close()

@app.post("/api/abha/request-otp")
def request_abha_otp(payload: ABHARequestOTP, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.abha_id == payload.abha_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="ABHA ID not registered")
    return {"status": "SUCCESS", "message": f"OTP sent for {payload.abha_id}"}

@app.post("/api/abha/verify-otp")
def verify_abha_otp(payload: ABHAVerifyOTP, db: Session = Depends(get_db)):
    if len(payload.otp) != 6 or not payload.otp.isdigit():
        raise HTTPException(status_code=400, detail="Invalid OTP")
    patient = db.query(Patient).filter(Patient.abha_id == payload.abha_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    consent_id = f"CNS-{int(datetime.utcnow().timestamp())}"
    consent = Consent(consent_id=consent_id, patient_id=patient.patient_id)
    db.add(consent)
    db.commit()
    return {"status": "VERIFIED", "patient": {"patient_id": patient.patient_id, "name": patient.name}}

@app.get("/api/patient/{patient_id}/timeline")
def get_patient_timeline(patient_id: str, db: Session = Depends(get_db)):
    return db.query(MedicalTimeline).filter(MedicalTimeline.patient_id == patient_id).all()

@app.post("/api/patient/submit-intake")
def submit_patient_intake(payload: PatientIntakeSubmit, db: Session = Depends(get_db)):
    event_id = f"EVT-{int(datetime.utcnow().timestamp())}"
    timeline_event = MedicalTimeline(
        event_id=event_id,
        patient_id=payload.patient_id,
        event_type="INTAKE_NOTE",
        title="Patient Intake & AYUSH Assessment",
        summary_data={"ayush_profile": payload.ayush_profile, "raw_transcript": payload.transcript}
    )
    db.add(timeline_event)
    db.commit()
    return {"status": "SUCCESS", "event_id": event_id}

@app.post("/api/ai/save-summary")
def save_ai_summary(payload: AISummaryPayload, db: Session = Depends(get_db)):
    event_id = f"AI-{int(datetime.utcnow().timestamp())}"
    ai_event = MedicalTimeline(
        event_id=event_id,
        patient_id=payload.patient_id,
        event_type="CLINICAL_SUMMARY",
        title="AI Processed Clinical Summary",
        summary_data={
            "chief_complaint": payload.chief_complaint,
            "hpi": payload.hpi,
            "past_meds": payload.past_meds,
            "lab_anomalies": payload.lab_anomalies,
            "is_emergency": payload.is_emergency,
            "emergency_reason": payload.emergency_reason
        }
    )
    db.add(ai_event)
    db.commit()
    return {"status": "SUCCESS"}

@app.get("/api/doctor/queue")
def get_doctor_queue(db: Session = Depends(get_db)):
    patients = db.query(Patient).all()
    queue = []
    for p in patients:
        latest = db.query(MedicalTimeline).filter(MedicalTimeline.patient_id == p.patient_id).order_by(MedicalTimeline.created_at.desc()).first()
        summary = latest.summary_data if latest else {}
        queue.append({
            "patient_id": p.patient_id,
            "name": p.name,
            "chief_complaint": summary.get("chief_complaint", "Pending AI Processing"),
            "is_emergency": summary.get("is_emergency", False)
        })
    return queue

@app.get("/api/patient/{patient_id}/fhir-export")
def export_fhir_bundle(patient_id: str, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return {
        "resourceType": "Bundle",
        "type": "document",
        "entry": [{"resource": {"resourceType": "Patient", "id": patient.patient_id, "name": [{"text": patient.name}]}}]
    }
