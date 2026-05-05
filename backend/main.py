"""
Inventory Management System — FastAPI Backend
Deploy on Railway. Connects to Supabase (PostgreSQL).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from supabase import Client, create_client

# ── Environment variables (set in Railway dashboard) ──────────────────────────
SUPABASE_URL: str = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY: str = os.environ["SUPABASE_SERVICE_KEY"]  # server-side only
SUPABASE_ANON_KEY: str = os.environ["SUPABASE_ANON_KEY"]        # for token verification

# ── Supabase client (service role — bypasses RLS for server ops) ──────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ── App setup ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # startup / shutdown hooks can go here

app = FastAPI(
    title="Inventory Management API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten to your Streamlit Cloud URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()


# ── Auth helper: verify Supabase JWT ─────────────────────────────────────────
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """
    Validates the Bearer token issued by Supabase Auth.
    Raises 401 if missing or invalid.
    """
    token = credentials.credentials
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "apikey": SUPABASE_ANON_KEY,
            },
        )
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again.",
        )
    return resp.json()


# ── Pydantic models ───────────────────────────────────────────────────────────

class AssetCreate(BaseModel):
    asset_tag: Optional[str] = None
    serial_number: Optional[str] = None
    part_number: Optional[str] = None
    po_number: Optional[str] = None
    description: str = Field(..., min_length=1)
    notes: Optional[str] = None
    quantity: int = Field(1, ge=0)
    price: Optional[float] = None
    category_id: Optional[int] = None
    department_id: Optional[int] = None
    campus_id: Optional[int] = None
    location_id: Optional[int] = None
    supplier_id: Optional[int] = None
    status_id: Optional[int] = None
    condition_id: Optional[int] = None
    purchase_date: Optional[str] = None                  # ISO date string
    date_placed_in_service: Optional[str] = None
    last_issued_or_transfer_date: Optional[str] = None
    day_disposed: Optional[str] = None
    last_day_scanned: Optional[str] = None


class AssetPatch(BaseModel):
    """Only the fields a user is allowed to update via PATCH."""
    status_id: Optional[int] = None
    condition_id: Optional[int] = None
    location_id: Optional[int] = None
    campus_id: Optional[int] = None
    notes: Optional[str] = None
    last_day_scanned: Optional[str] = None
    last_issued_or_transfer_date: Optional[str] = None
    day_disposed: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=0)


# ── Reference-data endpoints (public) ────────────────────────────────────────

@app.get("/ref/{table}", summary="Fetch a reference table")
def get_reference(table: str):
    allowed = {"categories", "departments", "campuses", "locations",
                "suppliers", "statuses", "conditions"}
    if table not in allowed:
        raise HTTPException(status_code=404, detail="Reference table not found.")
    result = supabase.table(table).select("*").order("name").execute()
    return result.data


# ── Asset endpoints ───────────────────────────────────────────────────────────

@app.get("/assets", summary="List assets with optional filters")
def list_assets(
    department: Optional[str] = Query(None, description="Filter by department name"),
    status: Optional[str] = Query(None, description="Filter by status name"),
    campus: Optional[str] = Query(None, description="Filter by campus name"),
    search: Optional[str] = Query(None, description="Search in description or asset_tag"),
    limit: int = Query(200, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Returns assets from the flattened `assets_view`.
    Supports filtering by department, status, campus, and a free-text search.
    """
    query = supabase.table("assets_view").select("*")

    if department:
        query = query.eq("department", department)
    if status:
        query = query.eq("status", status)
    if campus:
        query = query.eq("campus", campus)
    if search:
        # ilike on description OR asset_tag — Supabase supports `or` filter
        query = query.or_(
            f"description.ilike.%{search}%,asset_tag.ilike.%{search}%"
        )

    result = (
        query.order("id")
             .range(offset, offset + limit - 1)
             .execute()
    )
    return {"data": result.data, "count": len(result.data)}


@app.get("/assets/{asset_id}", summary="Get a single asset by ID")
def get_asset(asset_id: int):
    result = (
        supabase.table("assets_view")
        .select("*")
        .eq("id", asset_id)
        .single()
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found.")
    return result.data


@app.post("/assets", status_code=201, summary="Create a new asset [auth required]")
def create_asset(
    payload: AssetCreate,
    _user: dict = Depends(get_current_user),
):
    result = (
        supabase.table("assets")
        .insert(payload.model_dump(exclude_none=True))
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Insert failed.")
    return result.data[0]


@app.patch("/assets/{asset_id}", summary="Update asset status/location [auth required]")
def update_asset(
    asset_id: int,
    payload: AssetPatch,
    _user: dict = Depends(get_current_user),
):
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update.")

    result = (
        supabase.table("assets")
        .update(data)
        .eq("id", asset_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found.")
    return result.data[0]


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}
