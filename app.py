"""
Inventory Management System — Streamlit Frontend
Deploy on Google Cloud Run. Calls FastAPI backend also on Google Cloud Run.

Google Cloud configuration:
  - API URL read from Cloud Run environment variable CLOUD_RUN_API_URL
  - Database: Cloud SQL (PostgreSQL)
  - Authentication: Firebase Authentication
  - Secrets: Google Cloud Secret Manager
  - Port: 8080 (default for Cloud Run)
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date

import firebase_admin
import pandas as pd
import requests
import streamlit as st
from firebase_admin import auth as firebase_auth
from firebase_admin import credentials
from google.cloud import secretmanager

# ── Configure logging ────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Google Cloud Secret Manager Helper ───────────────────────────────────────
@st.cache_resource
def get_secret(secret_id: str, version_id: str = "latest") -> str:
    """Fetch a secret from Google Cloud Secret Manager."""
    try:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if not project_id:
            logger.warning("GOOGLE_CLOUD_PROJECT not set, using local mode")
            return os.environ.get(secret_id, "")
        
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        logger.error(f"Error fetching secret {secret_id}: {e}")
        # Fallback to environment variables
        return os.environ.get(secret_id, "")

# ── Firebase Authentication Setup ───────────────────────────────────────────
@st.cache_resource
def init_firebase():
    """Initialize Firebase Admin SDK."""
    try:
        if not firebase_admin._apps:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred)
        return True
    except Exception as e:
        logger.error(f"Firebase initialization error: {e}")
        st.error("Authentication service unavailable. Please try again later.")
        return False

# ── API URL Configuration ────────────────────────────────────────────────────
# Set in Cloud Run → Runtime settings → Environment variables
# Key:   CLOUD_RUN_API_URL
# Value: https://inventory-api-xxxxxxxx-uc.a.run.app
api_url = os.environ.get("CLOUD_RUN_API_URL", "http://localhost:8000")
API_URL: str = api_url

# ── Session state defaults ───────────────────────────────────────────────────
for key, default in [("access_token", None), ("user_email", None), ("loaded_asset", {})]:
    if key not in st.session_state:
        st.session_state[key] = default

# Initialize Firebase
if not init_firebase():
    st.stop()

# ── Helpers ──────────────────────────────────────────────────────────────────
def auth_headers() -> dict:
    """Generate authorization headers with Firebase token."""
    token = st.session_state.get("access_token")
    return {"Authorization": f"Bearer {token}"} if token else {}


@st.cache_data(ttl=300)
def fetch_ref(table: str) -> list[dict]:
    """Fetch reference data from API."""
    try:
        r = requests.get(f"{API_URL}/ref/{table}", timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Error fetching {table}: {e}")
        return []


def ref_map(table: str) -> dict[str, int]:
    """Map reference table names to IDs."""
    return {row["name"]: row["id"] for row in fetch_ref(table)}


# ── Page: Login ──────────────────────────────────────────────────────────────
def page_auth():
    st.title("🔐 Sign In")
    
    auth_tab, signup_tab = st.tabs(["Sign In", "Sign Up"])
    
    with auth_tab:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign In")
        
        if submitted:
            if not email or not password:
                st.error("Please enter email and password.")
                return
            
            try:
                # Verify with Firebase
                user = firebase_auth.get_user_by_email(email)
                
                # In production, you'd authenticate with a proper token
                # For now, we'll use Firebase's ID token
                # This requires a frontend SDK or a custom backend endpoint
                st.session_state["access_token"] = user.uid
                st.session_state["user_email"] = email
                st.success(f"✅ Logged in as {email}")
                st.rerun()
            except firebase_auth.UserNotFoundError:
                st.error("User not found. Please sign up first.")
            except Exception as e:
                st.error(f"Login failed: {str(e)}")
    
    with signup_tab:
        with st.form("signup_form"):
            new_email = st.text_input("Email", key="signup_email")
            new_password = st.text_input("Password", type="password", key="signup_password")
            confirm_password = st.text_input("Confirm Password", type="password", key="confirm_password")
            submit_signup = st.form_submit_button("Sign Up")
        
        if submit_signup:
            if not new_email or not new_password:
                st.error("Please fill in all fields.")
                return
            if new_password != confirm_password:
                st.error("Passwords do not match.")
                return
            
            try:
                # Create user in Firebase
                user = firebase_auth.create_user(
                    email=new_email,
                    password=new_password
                )
                st.success(f"✅ Account created successfully! Please sign in.")
                logger.info(f"New user created: {new_email}")
            except firebase_auth.EmailAlreadyExistsError:
                st.error("Email already exists.")
            except Exception as e:
                st.error(f"Sign up failed: {str(e)}")


# ── Page: Browse Assets ──────────────────────────────────────────────────────
def page_browse():
    st.title("📦 Asset Inventory")

    with st.sidebar:
        st.header("Filters")
        departments = [""] + [r["name"] for r in fetch_ref("departments")]
        statuses = [""] + [r["name"] for r in fetch_ref("statuses")]
        campuses = [""] + [r["name"] for r in fetch_ref("campuses")]

        dept = st.selectbox("Department", departments)
        status = st.selectbox("Status", statuses)
        campus = st.selectbox("Campus", campuses)
        search = st.text_input("Search description / tag")

    params: dict = {}
    if dept:
        params["department"] = dept
    if status:
        params["status"] = status
    if campus:
        params["campus"] = campus
    if search:
        params["search"] = search

    with st.spinner("Loading assets…"):
        try:
            r = requests.get(f"{API_URL}/assets", params=params, timeout=15)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            st.error(f"Could not load assets: {e}")
            logger.error(f"Error loading assets: {e}")
            return

    data = payload.get("data", [])
    st.caption(f"{len(data)} asset(s) found")

    if not data:
        st.info("No assets match your filters.")
        return

    display_cols = [
        "id",
        "asset_tag",
        "description",
        "category",
        "department",
        "status",
        "condition",
        "campus",
        "location",
        "quantity",
        "price",
    ]
    df = pd.DataFrame(data)
    existing = [c for c in display_cols if c in df.columns]
    st.dataframe(df[existing], use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Asset Detail")
    asset_id = st.number_input("Enter Asset ID to inspect", min_value=1, step=1, value=1)
    if st.button("Load Asset"):
        try:
            r2 = requests.get(f"{API_URL}/assets/{asset_id}", timeout=10)
            if r2.status_code == 404:
                st.warning("Asset not found.")
            else:
                r2.raise_for_status()
                st.json(r2.json())
        except Exception as e:
            st.error(str(e))
            logger.error(f"Error loading asset {asset_id}: {e}")


# ── Page: Add Asset ──────────────────────────────────────────────────────────
def page_add():
    if not st.session_state["access_token"]:
        st.warning("You must be logged in to add assets.")
        return

    st.title("➕ Add New Asset")

    cats = ref_map("categories")
    depts = ref_map("departments")
    cams = ref_map("campuses")
    locs = ref_map("locations")
    sups = ref_map("suppliers")
    stats = ref_map("statuses")
    conds = ref_map("conditions")

    with st.form("add_asset_form"):
        col1, col2 = st.columns(2)
        with col1:
            description = st.text_input("Description *")
            asset_tag = st.text_input("Asset Tag")
            serial_number = st.text_input("Serial Number")
            part_number = st.text_input("Part Number")
            po_number = st.text_input("PO Number")
            quantity = st.number_input("Quantity", min_value=0, value=1)
            price = st.number_input("Price ($)", min_value=0.0, format="%.2f")
        with col2:
            category_id = st.selectbox("Category", [""] + list(cats.keys()))
            department_id = st.selectbox("Department", [""] + list(depts.keys()))
            campus_id = st.selectbox("Campus", [""] + list(cams.keys()))
            location_id = st.selectbox("Location", [""] + list(locs.keys()))
            supplier_id = st.selectbox("Supplier", [""] + list(sups.keys()))
            status_id = st.selectbox("Status", [""] + list(stats.keys()))
            condition_id = st.selectbox("Condition", [""] + list(conds.keys()))

        st.subheader("Dates")
        d1, d2, d3 = st.columns(3)
        purchase_date = d1.date_input("Purchase Date", value=None)
        date_placed_in_service = d2.date_input("Date Placed in Service", value=None)
        last_day_scanned = d3.date_input("Last Day Scanned", value=None)

        notes = st.text_area("Notes")
        submitted = st.form_submit_button("Add Asset")

    if submitted:
        if not description:
            st.error("Description is required.")
            return

        body = {
            "description": description,
            "quantity": quantity,
            "price": price or None,
            "notes": notes or None,
            "asset_tag": asset_tag or None,
            "serial_number": serial_number or None,
            "part_number": part_number or None,
            "po_number": po_number or None,
            "category_id": cats.get(category_id),
            "department_id": depts.get(department_id),
            "campus_id": cams.get(campus_id),
            "location_id": locs.get(location_id),
            "supplier_id": sups.get(supplier_id),
            "status_id": stats.get(status_id),
            "condition_id": conds.get(condition_id),
            "purchase_date": str(purchase_date) if purchase_date else None,
            "date_placed_in_service": str(date_placed_in_service)
            if date_placed_in_service
            else None,
            "last_day_scanned": str(last_day_scanned) if last_day_scanned else None,
        }
        body = {k: v for k, v in body.items() if v is not None}

        try:
            r = requests.post(
                f"{API_URL}/assets",
                json=body,
                headers=auth_headers(),
                timeout=15,
            )
            if r.status_code == 201:
                st.success(f"✅ Asset created! ID: {r.json()['id']}")
                st.cache_data.clear()
            elif r.status_code == 401:
                st.error("Session expired — please log in again.")
            else:
                st.error(f"Error {r.status_code}: {r.text}")
        except Exception as e:
            st.error(str(e))
            logger.error(f"Error creating asset: {e}")


# ── Page: Update Asset ───────────────────────────────────────────────────────
def page_update():
    if not st.session_state["access_token"]:
        st.warning("You must be logged in to update assets.")
        return

    st.title("✏️ Update Asset Status / Location")

    stats = ref_map("statuses")
    conds = ref_map("conditions")
    cams = ref_map("campuses")
    locs = ref_map("locations")

    asset_id = st.number_input("Asset ID to update", min_value=1, step=1)

    if st.button("Load current values"):
        try:
            r = requests.get(f"{API_URL}/assets/{asset_id}", timeout=10)
            if r.status_code == 404:
                st.warning("Asset not found.")
            else:
                r.raise_for_status()
                st.session_state["loaded_asset"] = r.json()
        except Exception as e:
            st.error(str(e))
            logger.error(f"Error loading asset {asset_id}: {e}")

    loaded = st.session_state.get("loaded_asset", {})
    if loaded:
        st.info(
            f"Editing: **{loaded.get('description', '')}** (ID {loaded.get('id')})"
        )

    with st.form("update_form"):
        new_status = st.selectbox("New Status", ["(no change)"] + list(stats.keys()))
        new_condition = st.selectbox(
            "New Condition", ["(no change)"] + list(conds.keys())
        )
        new_campus = st.selectbox("New Campus", ["(no change)"] + list(cams.keys()))
        new_location = st.selectbox(
            "New Location", ["(no change)"] + list(locs.keys())
        )
        new_notes = st.text_area("Notes (leave blank to keep)")
        scan_today = st.checkbox("Mark as scanned today")
        submitted = st.form_submit_button("Update Asset")

    if submitted:
        body: dict = {}
        if new_status != "(no change)":
            body["status_id"] = stats[new_status]
        if new_condition != "(no change)":
            body["condition_id"] = conds[new_condition]
        if new_campus != "(no change)":
            body["campus_id"] = cams[new_campus]
        if new_location != "(no change)":
            body["location_id"] = locs[new_location]
        if new_notes.strip():
            body["notes"] = new_notes.strip()
        if scan_today:
            body["last_day_scanned"] = str(date.today())

        if not body:
            st.warning("Nothing to update.")
            return

        try:
            r = requests.patch(
                f"{API_URL}/assets/{asset_id}",
                json=body,
                headers=auth_headers(),
                timeout=15,
            )
            if r.status_code == 200:
                st.success("✅ Asset updated successfully.")
                st.cache_data.clear()
                st.session_state.pop("loaded_asset", None)
            elif r.status_code == 401:
                st.error("Session expired — please log in again.")
            elif r.status_code == 404:
                st.error("Asset not found.")
            else:
                st.error(f"Error {r.status_code}: {r.text}")
        except Exception as e:
            st.error(str(e))
            logger.error(f"Error updating asset {asset_id}: {e}")


# ── Navigation ───────────────────────────────────────────────────────────────
def main():
    st.set_page_config(
        page_title="Inventory Management System",
        page_icon="📦",
        layout="wide",
    )

    with st.sidebar:
        st.image("https://img.icons8.com/fluency/48/inventory.png", width=40)
        st.markdown("## 📦 Inventory System")
        st.divider()

        if st.session_state["access_token"]:
            st.success(f"👤 {st.session_state['user_email']}")
            if st.button("Log out"):
                st.session_state["access_token"] = None
                st.session_state["user_email"] = None
                st.rerun()
        else:
            st.info("Not logged in")

        st.divider()
        page = st.radio(
            "Navigate",
            ["Browse Assets", "Add Asset", "Update Asset", "Login"],
            label_visibility="collapsed",
        )

    if page == "Browse Assets":
        page_browse()
    elif page == "Add Asset":
        page_add()
    elif page == "Update Asset":
        page_update()
    elif page == "Login":
        page_auth()


if __name__ == "__main__":
    main()
