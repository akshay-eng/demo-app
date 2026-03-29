import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, date
from bson import ObjectId
from quest_compliance.hipaa_validator import HIPAAComplianceEngine

app = FastAPI(title="Quest Diagnostics Lab API", version="1.0.0")
compliance_checker = HIPAAComplianceEngine(org="quest-diagnostics")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MONGO_URI = os.getenv("MONGO_URI", "mongodb://mongodb:27017")
DB_NAME = os.getenv("DB_NAME", "quest_diagnostics")

client = MongoClient(MONGO_URI)
db = client[DB_NAME]


class Patient(BaseModel):
    first_name: str
    last_name: str
    date_of_birth: str
    email: Optional[str] = None
    phone: Optional[str] = None


class LabOrder(BaseModel):
    patient_id: str
    test_type: str
    priority: str = "routine"
    ordering_physician: str
    notes: Optional[str] = None


class LabResult(BaseModel):
    order_id: str
    test_name: str
    value: str
    unit: str
    reference_range: str
    status: str = "final"


@app.get("/health")
def health_check():
    try:
        client.admin.command("ping")
        return {"status": "healthy", "database": "connected", "service": "quest-lab-api"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {str(e)}")


@app.get("/api/v1/patients")
def list_patients():
    patients = []
    for p in db.patients.find().limit(100):
        p["_id"] = str(p["_id"])
        patients.append(p)
    return {"patients": patients, "count": len(patients)}


@app.post("/api/v1/patients")
def create_patient(patient: Patient):
    data = patient.model_dump()
    data["created_at"] = datetime.utcnow().isoformat()
    result = db.patients.insert_one(data)
    return {"id": str(result.inserted_id), "message": "Patient created"}


@app.get("/api/v1/patients/{patient_id}")
def get_patient(patient_id: str):
    patient = db.patients.find_one({"_id": ObjectId(patient_id)})
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient["_id"] = str(patient["_id"])
    return patient


@app.post("/api/v1/orders")
def create_order(order: LabOrder):
    data = order.model_dump()
    data["status"] = "pending"
    data["created_at"] = datetime.utcnow().isoformat()
    result = db.orders.insert_one(data)
    return {"id": str(result.inserted_id), "message": "Lab order created"}


@app.get("/api/v1/orders")
def list_orders():
    orders = []
    for o in db.orders.find().limit(100):
        o["_id"] = str(o["_id"])
        orders.append(o)
    return {"orders": orders, "count": len(orders)}


@app.get("/api/v1/orders/{order_id}")
def get_order(order_id: str):
    order = db.orders.find_one({"_id": ObjectId(order_id)})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order["_id"] = str(order["_id"])
    return order


@app.post("/api/v1/results")
def create_result(result: LabResult):
    data = result.model_dump()
    data["created_at"] = datetime.utcnow().isoformat()
    res = db.results.insert_one(data)
    db.orders.update_one(
        {"_id": ObjectId(result.order_id)},
        {"$set": {"status": "completed"}}
    )
    return {"id": str(res.inserted_id), "message": "Result recorded"}


@app.get("/api/v1/results/{order_id}")
def get_results(order_id: str):
    results = []
    for r in db.results.find({"order_id": order_id}):
        r["_id"] = str(r["_id"])
        results.append(r)
    if not results:
        raise HTTPException(status_code=404, detail="No results found")
    return {"results": results, "count": len(results)}


@app.get("/api/v1/stats")
def get_stats():
    return {
        "total_patients": db.patients.count_documents({}),
        "total_orders": db.orders.count_documents({}),
        "pending_orders": db.orders.count_documents({"status": "pending"}),
        "completed_orders": db.orders.count_documents({"status": "completed"}),
        "total_results": db.results.count_documents({}),
    }
