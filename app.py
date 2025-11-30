import streamlit as st
from typing import Any
import json
import io
import csv
import pdfplumber
import pandas as pd
from api_client import APIClient
from datetime import date



# ---------- Helpers ----------

CATEGORY_OPTIONS = [
    "SALES",
    "STOCK",
    "FUEL",
    "DATA_AIRTIME",
    "RENT",
    "EQUIPMENT",
    "TRANSPORT",
    "FOOD",
    "MISC",
]


def get_client() -> APIClient:
    if "api_client" not in st.session_state:
        st.session_state.api_client = APIClient()
    return st.session_state.api_client


def get_auth_state():
    if "auth" not in st.session_state:
        st.session_state.auth = {
            "access_token": None,
            "refresh_token": None,
            "user": None,
        }
    return st.session_state.auth


def require_login() -> bool:
    auth = get_auth_state()
    if not auth["access_token"]:
        st.warning("You need to be logged in to use this feature.")
        st.info("Use the 'Account' page in the sidebar to log in or register.")
        return False
    return True


def show_api_error(error: Any):
    if isinstance(error, dict) and "error" in error:
        st.error(str(error.get("error")))
        details = error.get("details")
        if details:
            st.write(details)
    else:
        st.error(str(error))


def load_profile_if_needed():
    auth = get_auth_state()
    if not auth["access_token"]:
        return None

    client = get_client()
    if "profile_data" not in st.session_state:
        ok, data = client.get_profile(auth["access_token"])
        if ok:
            st.session_state.profile_data = data
        else:
            st.session_state.profile_data = None
            show_api_error(data)
            return None

    return st.session_state.profile_data


def format_employment_tag(profile: dict | None) -> str:
    if not profile:
        return "Profile not set"

    etype = (profile.get("employmentType") or "INFORMAL").upper()
    mapping = {
        "EMPLOYEE": "Employee",
        "SELF_EMPLOYED": "Self-employed",
        "BOTH": "Employee & Self-employed",
        "UNEMPLOYED": "Unemployed",
        "INFORMAL": "Informal / Hustle",
    }
    return mapping.get(etype, "Other")

def parse_gtbank_pdf_to_rows(file_bytes: bytes):
    """
    Parse a GTBank-style PDF statement into preview_rows and backend_rows.

    - preview_rows: for showing in Streamlit
    - backend_rows: in the shape expected by the backend importStatement API
      [{ date, description, amount, direction, reference, counterparty }]
    """
    preview_rows = []
    backend_rows = []

    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if not tables:
                continue

            for table in tables:
                if not table:
                    continue

                # Skip header rows until we get to actual data
                for row in table:
                    if not row:
                        continue

                    # Typical header row contains 'Trans' and 'Debit'
                    joined = " ".join([cell or "" for cell in row])
                    if "Trans" in joined and "Debit" in joined:
                        # header row; skip
                        continue

                    # Expect something like:
                    # [Trans Date, Reference, Value Date, Debit, Credit, Balance, Remarks]
                    # But pdfplumber may return shorter/longer; be defensive.
                    if len(row) < 5:
                        continue

                    trans_date = (row[0] or "").strip()
                    reference = (row[1] or "").strip()
                    value_date = (row[2] or "").strip()
                    debit_str = (row[3] or "").replace(",", "").strip()
                    credit_str = (row[4] or "").replace(",", "").strip()
                    balance = (row[5] or "").strip() if len(row) > 5 else ""
                    remarks = (row[6] or "").strip() if len(row) > 6 else ""

                    if not trans_date:
                        # Often the table ends with blank rows; skip
                        continue

                    # Parse amounts; treat blanks as 0
                    try:
                        debit = float(debit_str) if debit_str not in ("", None) else 0.0
                    except ValueError:
                        debit = 0.0
                    try:
                        credit = float(credit_str) if credit_str not in ("", None) else 0.0
                    except ValueError:
                        credit = 0.0

                    if debit == 0.0 and credit == 0.0:
                        # Not a real transaction row
                        continue

                    # Description = reference + remarks
                    desc_parts = [reference, remarks]
                    description = " ".join(p for p in desc_parts if p).strip()
                    if not description:
                        description = reference or remarks or ""

                    if credit > 0:
                        direction = "INCOME"
                        amount = credit
                    else:
                        direction = "EXPENSE"
                        amount = debit

                    backend_rows.append(
                        {
                            "date": trans_date,          # keep as string; backend accepts string
                            "description": description,
                            "amount": amount,
                            "direction": direction,
                            "reference": reference or None,
                            "counterparty": None,
                        }
                    )

                    preview_rows.append(
                        {
                            "date": trans_date,
                            "reference": reference,
                            "value_date": value_date,
                            "debit": debit,
                            "credit": credit,
                            "balance": balance,
                            "remarks": remarks,
                            "mapped_direction": direction,
                            "mapped_amount": amount,
                        }
                    )

    return preview_rows, backend_rows


# ---------- Explanation helpers ----------

def explain_pit_output(output: dict):
    st.subheader("Explanation (PIT)")

    total_tax = output.get("totalTax", 0) or 0
    taxable_income = output.get("taxableIncome", 0) or 0
    effective_rate = output.get("effectiveRate", 0) or 0
    deductions = output.get("deductions", {}) or {}
    bands = output.get("bands", []) or []

    pension = deductions.get("pension", 0) or 0
    nhf = deductions.get("nhf", 0) or 0
    rent_relief = deductions.get("rentRelief", 0) or 0

    gross_income = taxable_income + pension + nhf + rent_relief

    st.markdown(
        f"""
- Your **gross annual income** is approximately **₦{gross_income:,.2f}**.
- After deducting **pension (₦{pension:,.2f})**, **NHF (₦{nhf:,.2f})** and **rent relief (₦{rent_relief:,.2f})**, your **taxable income** is **₦{taxable_income:,.2f}**.
- Based on the current PIT bands, your **total annual tax** is **₦{total_tax:,.2f}**, which is an **effective tax rate** of **{effective_rate * 100:.2f}%** of your gross income.
        """
    )

    if not bands:
        st.info("No band breakdown was returned for this calculation.")
        return

    st.markdown("### How your income was taxed by band")

    for i, band in enumerate(bands):
        if i >= 5:
            st.caption("Additional bands omitted for brevity.")
            break

        threshold = band.get("threshold")
        rate = band.get("rate", 0) or 0
        applied = band.get("appliedTo", 0) or 0
        tax = band.get("tax", 0) or 0

        if threshold is None:
            band_label = "Income above the last band"
        else:
            band_label = f"Up to ₦{threshold:,.0f}"

        st.markdown(
            f"- **{band_label}**: ₦{applied:,.2f} taxed at **{rate * 100:.1f}%** → **₦{tax:,.2f}**"
        )


def explain_paye_output(output: dict):
    st.subheader("Explanation (PAYE)")

    annual_income = output.get("annualIncome", 0) or 0
    expected_annual_tax = output.get("expectedAnnualTax", 0) or 0
    expected_monthly = output.get("expectedMonthlyPaye", 0) or 0
    actual = output.get("actualMonthlyPaye", 0) or 0
    diff = output.get("difference", 0) or 0
    direction = output.get("differenceDirection", "MATCH") or "MATCH"
    effective_rate = output.get("effectiveRate", 0) or 0

    deductions = output.get("deductions", {}) or {}
    pension = deductions.get("pension", 0) or 0
    nhf = deductions.get("nhf", 0) or 0
    rent_relief = deductions.get("rentRelief", 0) or 0

    st.markdown(
        f"""
- Your **annual gross income** is about **₦{annual_income:,.2f}**.
- After pension (**₦{pension:,.2f}**), NHF (**₦{nhf:,.2f}**) and rent relief (**₦{rent_relief:,.2f}**), the system expects your **annual tax** to be **₦{expected_annual_tax:,.2f}**.
- This works out to an **expected PAYE per month** of **₦{expected_monthly:,.2f}** and an **effective tax rate** of **{effective_rate * 100:.2f}%** of your gross income.
        """
    )

    if direction == "MATCH":
        st.markdown(
            f"- Your employer is deducting about **₦{actual:,.2f}** per month, which **matches** the expected PAYE."
        )
    elif direction == "OVERPAID":
        st.markdown(
            f"- Your employer is deducting **₦{actual:,.2f}** per month, which is about **₦{abs(diff):,.2f} more** than the expected PAYE."
        )
    elif direction == "UNDERPAID":
        st.markdown(
            f"- Your employer is deducting **₦{actual:,.2f}** per month, which is about **₦{abs(diff):,.2f} less** than the expected PAYE."
        )
    elif direction == "NO_ACTUAL":
        st.markdown(
            "- You did not provide an actual PAYE figure, so only the **expected** PAYE has been calculated."
        )

    bands = output.get("pitBands") or output.get("bands") or []
    if bands:
        st.markdown("### How your PAYE was derived from PIT bands")
        for i, band in enumerate(bands):
            if i >= 5:
                st.caption("Additional bands omitted for brevity.")
                break

            threshold = band.get("threshold")
            rate = band.get("rate", 0) or 0
            applied = band.get("appliedTo", 0) or 0
            tax = band.get("tax", 0) or 0

            if threshold is None:
                band_label = "Income above the last band"
            else:
                band_label = f"Up to ₦{threshold:,.0f}"

            st.markdown(
                f"- **{band_label}**: ₦{applied:,.2f} taxed at **{rate * 100:.1f}%** → **₦{tax:,.2f}**"
            )


def render_downloads_for_calc(calc: dict):
    st.subheader("Download")

    calc_id = calc.get("id", "unknown")
    output = calc.get("output") or {}
    calc_type = calc.get("type", "UNKNOWN")

    # Full JSON
    json_bytes = json.dumps(calc, indent=2, default=str).encode("utf-8")
    st.download_button(
        "Download full calculation (JSON)",
        data=json_bytes,
        file_name=f"tax_calc_{calc_id}.json",
        mime="application/json",
    )

    # Band breakdown as CSV (if present)
    bands = None
    if calc_type == "PIT":
        bands = output.get("bands") or []
    elif calc_type == "PAYE":
        bands = output.get("pitBands") or output.get("bands") or []

    if bands:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["band_upper_limit", "rate_percent", "applied_amount", "tax"])
        for b in bands:
            threshold = b.get("threshold")
            rate = (b.get("rate") or 0) * 100
            applied = b.get("appliedTo") or 0
            tax = b.get("tax") or 0
            writer.writerow([threshold, f"{rate:.2f}", f"{applied:.2f}", f"{tax:.2f}"])

        csv_bytes = buf.getvalue().encode("utf-8")
        st.download_button(
            "Download band breakdown (CSV)",
            data=csv_bytes,
            file_name=f"tax_calc_{calc_id}_bands.csv",
            mime="text/csv",
        )

    # Optional PDF summary
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        pdf_buf = io.BytesIO()
        c = canvas.Canvas(pdf_buf, pagesize=A4)
        width, height = A4

        y = height - 50
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "TaxMate Nigeria - Calculation Summary")
        y -= 30

        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"ID: {calc_id}")
        y -= 15
        c.drawString(50, y, f"Type: {calc_type}")
        y -= 15
        c.drawString(50, y, f"Assessment year: {calc.get('assessmentYear')}")
        y -= 25

        total_tax = output.get("totalTax") or output.get("expectedAnnualTax") or 0
        eff = output.get("effectiveRate") or 0
        c.drawString(50, y, f"Total / expected annual tax: ₦{total_tax:,.2f}")
        y -= 15
        c.drawString(50, y, f"Effective rate: {eff * 100:.2f}%")
        y -= 25

        c.drawString(50, y, "This summary is generated automatically from your calculation.")
        y -= 15

        c.showPage()
        c.save()
        pdf_bytes = pdf_buf.getvalue()

        st.download_button(
            "Download summary (PDF)",
            data=pdf_bytes,
            file_name=f"tax_calc_{calc_id}_summary.pdf",
            mime="application/pdf",
        )
    except ImportError:
        st.info("Install 'reportlab' to enable PDF download (pip install reportlab).")


# ---------- Page: Account ----------

def page_account():
    st.header("Account")

    auth = get_auth_state()
    client = get_client()

    if auth["access_token"]:
        st.success(f"Logged in as {auth['user'].get('email')}")
        if st.button("Log out"):
            auth["access_token"] = None
            auth["refresh_token"] = None
            auth["user"] = None
            st.success("Logged out.")
        return

    tab_login, tab_register = st.tabs(["Login", "Register"])

    with tab_login:
        st.subheader("Login")
        login_email = st.text_input("Email", key="login_email")
        login_password = st.text_input("Password", type="password", key="login_password")
        if st.button("Login"):
            if not login_email or not login_password:
                st.error("Email and password are required.")
            else:
                ok, data = client.login(login_email, login_password)
                if ok:
                    auth["access_token"] = data.get("accessToken")
                    auth["refresh_token"] = data.get("refreshToken")
                    auth["user"] = data.get("user")
                    st.success("Logged in successfully.")
                else:
                    show_api_error(data)

    with tab_register:
        st.subheader("Register")
        reg_email = st.text_input("Email", key="reg_email")
        reg_password = st.text_input("Password", type="password", key="reg_password")
        if st.button("Create account"):
            if not reg_email or not reg_password:
                st.error("Email and password are required.")
            else:
                ok, data = client.register(reg_email, reg_password)
                if ok:
                    auth["access_token"] = data.get("accessToken")
                    auth["refresh_token"] = data.get("refreshToken")
                    auth["user"] = data.get("user")
                    st.success("Account created and logged in.")
                else:
                    show_api_error(data)


# ---------- Page: Quick PIT ----------

def page_quick_pit():
    st.header("Quick Tax Check (PIT)")

    st.write(
        "Use this quick calculator to estimate your annual personal income tax under the new rules. "
        "No login required."
    )

    client = get_client()

    with st.form("quick_pit_form"):
        col1, col2 = st.columns(2)
        with col1:
            annual_income = st.number_input(
                "Annual income (₦)",
                min_value=0.0,
                value=3_000_000.0,
                step=50_000.0,
                format="%.2f",
            )
            assessment_year = st.number_input(
                "Assessment year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
            )
        with col2:
            annual_rent = st.number_input(
                "Annual rent (₦)",
                min_value=0.0,
                value=600_000.0,
                step=50_000.0,
                format="%.2f",
            )
            pension_rate = st.number_input(
                "Pension rate (%)",
                min_value=0.0,
                max_value=30.0,
                value=8.0,
                step=0.5,
            )
            nhf_rate = st.number_input(
                "NHF rate (%) (optional)",
                min_value=0.0,
                max_value=20.0,
                value=0.0,
                step=0.5,
            )

        rent_status = st.selectbox(
            "Rent status",
            options=["TENANT", "OWNER_OCCUPIER", "OTHER"],
            index=0,
        )

        is_minimum_wage = st.checkbox("My income is at or below minimum wage")

        submitted = st.form_submit_button("Calculate")

    if submitted:
        pension_amount = annual_income * pension_rate / 100.0
        nhf_amount = annual_income * nhf_rate / 100.0

        st.caption(
            f"Using pension ₦{pension_amount:,.2f} ({pension_rate:.1f}%) and "
            f"NHF ₦{nhf_amount:,.2f} ({nhf_rate:.1f}%) of income."
        )

        payload = {
            "assessmentYear": int(assessment_year),
            "annualIncome": float(annual_income),
            "annualRent": float(annual_rent),
            "pension": float(pension_amount),
            "nhf": float(nhf_amount),
            "rentStatus": rent_status,
            "isMinimumWage": bool(is_minimum_wage),
        }

        ok, data = client.quick_pit(payload)
        if ok:
            st.subheader("Result")

            total_tax = data.get("totalTax", 0)
            effective_rate = data.get("effectiveRate", 0)
            taxable_income = data.get("taxableIncome", 0)
            deductions = data.get("deductions", {})

            st.metric("Estimated annual tax (₦)", f"{total_tax:,.2f}")
            st.metric("Effective tax rate", f"{effective_rate * 100:.2f}%")
            st.metric("Taxable income (₦)", f"{taxable_income:,.2f}")

            with st.expander("Deductions"):
                st.write(deductions)

            bands = data.get("bands", [])
            if bands:
                with st.expander("Band breakdown"):
                    st.table(
                        [
                            {
                                "Band upper limit": b.get("threshold"),
                                "Rate": f"{b.get('rate', 0) * 100:.1f}%",
                                "Applied to (₦)": f"{b.get('appliedTo', 0):,.2f}",
                                "Tax (₦)": f"{b.get('tax', 0):,.2f}",
                            }
                            for b in bands
                        ]
                    )
        else:
            show_api_error(data)


# ---------- Page: Self-employed Quick Check ----------

def page_self_employed_quick():
    st.header("Self-Employed Quick Check")

    st.write(
        "Estimate your tax based on your hustle income and costs. "
        "Works well for POS agents, online sellers, freelancers, etc."
    )

    client = get_client()

    with st.form("self_employed_quick_form"):
        col1, col2 = st.columns(2)
        with col1:
            total_sales = st.number_input(
                "Total money you collected (sales) for the period (₦)",
                min_value=0.0,
                value=2_000_000.0,
                step=50_000.0,
                format="%.2f",
            )
            goods_cost = st.number_input(
                "How much you spent on goods/stock (₦)",
                min_value=0.0,
                value=800_000.0,
                step=50_000.0,
                format="%.2f",
            )
            other_expenses = st.number_input(
                "Other running costs (fuel, data, etc.) for the period (₦)",
                min_value=0.0,
                value=200_000.0,
                step=25_000.0,
                format="%.2f",
            )
        with col2:
            period_months = st.number_input(
                "Period covered (months)",
                min_value=1,
                max_value=24,
                value=12,
                step=1,
            )
            annual_rent = st.number_input(
                "Annual shop/stall rent (₦)",
                min_value=0.0,
                value=0.0,
                step=50_000.0,
                format="%.2f",
            )
            pension_rate = st.number_input(
                "Pension rate on your profit (%)",
                min_value=0.0,
                max_value=30.0,
                value=8.0,
                step=0.5,
            )
            nhf_rate = st.number_input(
                "NHF rate on your profit (%) (optional)",
                min_value=0.0,
                max_value=20.0,
                value=0.0,
                step=0.5,
            )

        rent_status = st.selectbox(
            "Rent status",
            options=["TENANT", "OWNER_OCCUPIER", "OTHER"],
            index=0,
        )

        assessment_year = st.number_input(
            "Assessment year",
            min_value=2000,
            max_value=2100,
            value=2026,
            step=1,
        )

        is_minimum_wage = st.checkbox("My profit is at or below minimum wage level")

        submitted = st.form_submit_button("Estimate tax from my hustle")

    if submitted:
        period_profit = total_sales - goods_cost - other_expenses
        if period_months > 0:
            annual_profit = period_profit * (12 / period_months)
        else:
            annual_profit = period_profit

        pension_amount = max(0.0, annual_profit) * pension_rate / 100.0
        nhf_amount = max(0.0, annual_profit) * nhf_rate / 100.0

        st.caption(
            f"Estimated profit for the period: ₦{period_profit:,.2f}. "
            f"Annualised profit: ₦{annual_profit:,.2f}."
        )
        st.caption(
            f"Pension on profit: ₦{pension_amount:,.2f} ({pension_rate:.1f}%), "
            f"NHF on profit: ₦{nhf_amount:,.2f} ({nhf_rate:.1f}%)."
        )

        payload = {
            "assessmentYear": int(assessment_year),
            "periodMonths": int(period_months),
            "totalSales": float(total_sales),
            "goodsCost": float(goods_cost),
            "otherExpenses": float(other_expenses),
            "annualRent": float(annual_rent),
            "pensionRate": float(pension_rate),
            "nhfRate": float(nhf_rate),
            "rentStatus": rent_status,
            "isMinimumWage": bool(is_minimum_wage),
        }

        ok, data = client.self_employed_quick(payload)
        if ok:
            st.subheader("Result")

            annual_profit_backend = data.get("annualProfit", 0)
            total_tax = data.get("totalTax", 0)
            effective_rate = data.get("effectiveRate", 0)

            st.metric("Annual profit used for tax (₦)", f"{annual_profit_backend:,.2f}")
            st.metric("Estimated annual tax (₦)", f"{total_tax:,.2f}")
            st.metric("Effective tax rate on profit", f"{effective_rate * 100:.2f}%")

            monthly_tax = total_tax / 12 if total_tax else 0
            st.metric("Rough tax per month (₦)", f"{monthly_tax:,.2f}")

            with st.expander("Details"):
                st.json(data)
        else:
            show_api_error(data)


# ---------- Page: Detailed PIT ----------

def page_pit():
    st.header("Detailed PIT Calculator")

    if not require_login():
        return

    auth = get_auth_state()
    client = get_client()

    profile = load_profile_if_needed()
    use_defaults_key = "use_profile_defaults_pit"

    if profile:
        st.checkbox(
            "Apply profile defaults",
            key=use_defaults_key,
            value=st.session_state.get(use_defaults_key, True),
            help="Use your saved income, rent, rent status, pension and NHF rates as defaults."
        )

    use_defaults = st.session_state.get(use_defaults_key, False)

    default_annual_income = 3_000_000.0
    default_annual_rent = 600_000.0
    default_pension_rate = 8.0
    default_nhf_rate = 0.0
    default_rent_status = "TENANT"

    if profile and use_defaults:
        if profile.get("defaultMonthlyIncome") is not None:
            default_annual_income = float(profile["defaultMonthlyIncome"]) * 12.0
        if profile.get("defaultAnnualRent") is not None:
            default_annual_rent = float(profile["defaultAnnualRent"])
        if profile.get("defaultPensionRate") is not None:
            default_pension_rate = float(profile["defaultPensionRate"])
        if profile.get("defaultNhfRate") is not None:
            default_nhf_rate = float(profile["defaultNhfRate"])
        if profile.get("rentStatus"):
            default_rent_status = profile["rentStatus"]

    with st.form("pit_form"):
        col1, col2 = st.columns(2)
        with col1:
            assessment_year = st.number_input(
                "Assessment year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
            )
            annual_income = st.number_input(
                "Annual income (₦)",
                min_value=0.0,
                value=default_annual_income,
                step=50_000.0,
                format="%.2f",
            )
        with col2:
            pension_rate = st.number_input(
                "Pension rate (%)",
                min_value=0.0,
                max_value=30.0,
                value=default_pension_rate,
                step=0.5,
            )
            nhf_rate = st.number_input(
                "NHF rate (%) (optional)",
                min_value=0.0,
                max_value=20.0,
                value=default_nhf_rate,
                step=0.5,
            )
            annual_rent = st.number_input(
                "Annual rent (₦)",
                min_value=0.0,
                value=default_annual_rent,
                step=50_000.0,
                format="%.2f",
            )

        rent_status = st.selectbox(
            "Rent status",
            options=["TENANT", "OWNER_OCCUPIER", "OTHER"],
            index=["TENANT", "OWNER_OCCUPIER", "OTHER"].index(default_rent_status),
        )

        is_minimum_wage = st.checkbox("My income is at or below minimum wage")

        submitted = st.form_submit_button("Calculate and save")

    if submitted:
        pension_amount = annual_income * pension_rate / 100.0
        nhf_amount = annual_income * nhf_rate / 100.0

        st.caption(
            f"Using pension ₦{pension_amount:,.2f} ({pension_rate:.1f}%) and "
            f"NHF ₦{nhf_amount:,.2f} ({nhf_rate:.1f}%) of income."
        )

        payload = {
            "assessmentYear": int(assessment_year),
            "annualIncome": float(annual_income),
            "pension": float(pension_amount),
            "nhf": float(nhf_amount),
            "annualRent": float(annual_rent),
            "rentStatus": rent_status,
            "isMinimumWage": bool(is_minimum_wage),
        }

        ok, data = client.pit(payload, auth["access_token"])
        if ok:
            st.subheader("Result")

            total_tax = data.get("totalTax", 0)
            effective_rate = data.get("effectiveRate", 0)
            taxable_income = data.get("taxableIncome", 0)
            deductions = data.get("deductions", {})

            st.metric("Annual tax (₦)", f"{total_tax:,.2f}")
            st.metric("Effective tax rate", f"{effective_rate * 100:.2f}%")
            st.metric("Taxable income (₦)", f"{taxable_income:,.2f}")

            with st.expander("Deductions"):
                st.write(deductions)

            bands = data.get("bands", [])
            if bands:
                with st.expander("Band breakdown"):
                    st.table(
                        [
                            {
                                "Band upper limit": b.get("threshold"),
                                "Rate": f"{b.get('rate', 0) * 100:.1f}%",
                                "Applied to (₦)": f"{b.get('appliedTo', 0):,.2f}",
                                "Tax (₦)": f"{b.get('tax', 0):,.2f}",
                            }
                            for b in bands
                        ]
                    )

            st.info("This calculation has been saved under your account in the backend.")
        else:
            show_api_error(data)


# ---------- Page: PAYE Checker ----------

def page_paye():
    st.header("PAYE Checker")

    if not require_login():
        return

    auth = get_auth_state()
    client = get_client()

    profile = load_profile_if_needed()
    use_defaults_key = "use_profile_defaults_paye"

    if profile:
        st.checkbox(
            "Apply profile defaults",
            key=use_defaults_key,
            value=st.session_state.get(use_defaults_key, True),
            help="Use your saved income, rent, rent status, pension and NHF rates as defaults."
        )

    use_defaults = st.session_state.get(use_defaults_key, False)

    default_monthly_income = 350_000.0
    default_annual_rent = 600_000.0
    default_pension_rate = 8.0
    default_nhf_rate = 0.0
    default_rent_status = "TENANT"

    if profile and use_defaults:
        if profile.get("defaultMonthlyIncome") is not None:
            default_monthly_income = float(profile["defaultMonthlyIncome"])
        if profile.get("defaultAnnualRent") is not None:
            default_annual_rent = float(profile["defaultAnnualRent"])
        if profile.get("defaultPensionRate") is not None:
            default_pension_rate = float(profile["defaultPensionRate"])
        if profile.get("defaultNhfRate") is not None:
            default_nhf_rate = float(profile["defaultNhfRate"])
        if profile.get("rentStatus"):
            default_rent_status = profile["rentStatus"]

    with st.form("paye_form"):
        col1, col2 = st.columns(2)
        with col1:
            assessment_year = st.number_input(
                "Assessment year",
                min_value=2000,
                max_value=2100,
                value=2026,
                step=1,
            )
            monthly_income = st.number_input(
                "Monthly gross income (₦)",
                min_value=0.0,
                value=default_monthly_income,
                step=10_000.0,
                format="%.2f",
            )
            pension_rate = st.number_input(
                "Pension rate (% of monthly income)",
                min_value=0.0,
                max_value=30.0,
                value=default_pension_rate,
                step=0.5,
            )
        with col2:
            nhf_rate = st.number_input(
                "NHF rate (% of monthly income, optional)",
                min_value=0.0,
                max_value=20.0,
                value=default_nhf_rate,
                step=0.5,
            )
            annual_rent = st.number_input(
                "Annual rent (₦)",
                min_value=0.0,
                value=default_annual_rent,
                step=50_000.0,
                format="%.2f",
            )
            actual_paye = st.number_input(
                "Actual PAYE deducted per month (₦)",
                min_value=0.0,
                value=30_000.0,
                step=1_000.0,
                format="%.2f",
            )

        rent_status = st.selectbox(
            "Rent status",
            options=["TENANT", "OWNER_OCCUPIER", "OTHER"],
            index=["TENANT", "OWNER_OCCUPIER", "OTHER"].index(default_rent_status),
        )

        is_minimum_wage = st.checkbox("My income is at or below minimum wage")

        submitted = st.form_submit_button("Check PAYE")

    if submitted:
        monthly_pension = monthly_income * pension_rate / 100.0
        monthly_nhf = monthly_income * nhf_rate / 100.0

        st.caption(
            f"Using pension ₦{monthly_pension:,.2f} ({pension_rate:.1f}%) and "
            f"NHF ₦{monthly_nhf:,.2f} ({nhf_rate:.1f}%) per month."
        )

        payload = {
            "assessmentYear": int(assessment_year),
            "monthlyIncome": float(monthly_income),
            "monthlyPension": float(monthly_pension),
            "monthlyNhf": float(monthly_nhf),
            "annualRent": float(annual_rent),
            "rentStatus": rent_status,
            "isMinimumWage": bool(is_minimum_wage),
            "actualMonthlyPaye": float(actual_paye),
        }

        ok, data = client.paye(payload, auth["access_token"])
        if ok:
            st.subheader("Result")

            expected_monthly = data.get("expectedMonthlyPaye", 0)
            actual = data.get("actualMonthlyPaye", 0)
            diff = data.get("difference", 0)
            direction = data.get("differenceDirection", "MATCH")
            effective_rate = data.get("effectiveRate", 0)

            st.metric("Expected PAYE per month (₦)", f"{expected_monthly:,.2f}")
            st.metric("Actual PAYE per month (₦)", f"{actual:,.2f}")
            st.metric("Difference (₦)", f"{diff:,.2f}")
            st.metric("Effective annual tax rate", f"{effective_rate * 100:.2f}%")

            msg_map = {
                "MATCH": "Your employer's PAYE deduction is in line with expectations.",
                "OVERPAID": "It looks like you may be paying more PAYE than expected.",
                "UNDERPAID": "It looks like your PAYE deduction may be less than expected.",
                "NO_ACTUAL": "No actual PAYE provided; only expected PAYE has been calculated.",
            }
            st.info(msg_map.get(direction, "Result computed."))

            with st.expander("Details"):
                st.json(data)
        else:
            show_api_error(data)


# ---------- Page: Profile & Defaults ----------

def page_profile():
    st.header("Profile & Defaults")

    if not require_login():
        return

    auth = get_auth_state()
    client = get_client()

    profile = load_profile_if_needed()
    if profile is None:
        return

    st.write("Set your default details so you don't have to fill them in every time.")

    with st.form("profile_form"):
        full_name = st.text_input("Full name", value=profile.get("fullName") or "")

        col1, col2 = st.columns(2)
        with col1:
            state = st.text_input(
                "State of residence",
                value=profile.get("stateOfResidence") or ""
            )
            employment_type = st.selectbox(
                "Employment type",
                options=["EMPLOYEE", "SELF_EMPLOYED", "BOTH", "UNEMPLOYED", "INFORMAL"],
                index=[
                    "EMPLOYEE", "SELF_EMPLOYED", "BOTH", "UNEMPLOYED", "INFORMAL"
                ].index(profile.get("employmentType") or "INFORMAL"),
            )
        with col2:
            default_monthly_income = st.number_input(
                "Typical monthly income (₦)",
                min_value=0.0,
                value=float(profile.get("defaultMonthlyIncome") or 0.0),
                step=10_000.0,
                format="%.2f",
            )
            default_annual_rent = st.number_input(
                "Typical annual rent (₦)",
                min_value=0.0,
                value=float(profile.get("defaultAnnualRent") or 0.0),
                step=50_000.0,
                format="%.2f",
            )

        rent_status = st.selectbox(
            "Rent status",
            options=["TENANT", "OWNER_OCCUPIER", "OTHER", "UNKNOWN"],
            index=[
                "TENANT", "OWNER_OCCUPIER", "OTHER", "UNKNOWN"
            ].index(profile.get("rentStatus") or "TENANT"),
        )

        col3, col4 = st.columns(2)
        with col3:
            default_pension_rate = st.number_input(
                "Default pension rate (%)",
                min_value=0.0,
                max_value=30.0,
                value=float(profile.get("defaultPensionRate") or 8.0),
                step=0.5,
            )
        with col4:
            default_nhf_rate = st.number_input(
                "Default NHF rate (%) (optional)",
                min_value=0.0,
                max_value=20.0,
                value=float(profile.get("defaultNhfRate") or 0.0),
                step=0.5,
            )

        submitted = st.form_submit_button("Save profile")

    if submitted:
        payload = {
            "fullName": full_name or None,
            "stateOfResidence": state or None,
            "employmentType": employment_type,
            "defaultMonthlyIncome": default_monthly_income or None,
            "defaultAnnualRent": default_annual_rent or None,
            "rentStatus": rent_status,
            "defaultPensionRate": default_pension_rate,
            "defaultNhfRate": default_nhf_rate if default_nhf_rate > 0 else None,
        }

        ok, data = client.update_profile(payload, auth["access_token"])
        if ok:
            st.session_state.profile_data = data
            st.success("Profile updated.")
        else:
            show_api_error(data)


# ---------- Page: My Tax History ----------

def page_history():
    st.header("My Tax History")

    if not require_login():
        return

    auth = get_auth_state()
    client = get_client()

    profile = load_profile_if_needed()
    employment_tag = format_employment_tag(profile)

    ok, data = client.list_calculations(auth["access_token"])
    if not ok:
        show_api_error(data)
        return

    calcs = data or []
    if not calcs:
        st.info("You don't have any saved calculations yet.")
        return

    pit_calcs = [c for c in calcs if c.get("type") == "PIT"]
    paye_calcs = [c for c in calcs if c.get("type") == "PAYE"]

    st.subheader("Summary")

    col_pit, col_paye = st.columns(2)
    with col_pit:
        st.metric("PIT calculations", len(pit_calcs))
        st.caption(f"Profile tag: {employment_tag}")
    with col_paye:
        st.metric("PAYE calculations", len(paye_calcs))
        st.caption(f"Profile tag: {employment_tag}")

    st.markdown("---")

    selected_id_key = "selected_calc_id"
    if selected_id_key not in st.session_state:
        st.session_state[selected_id_key] = None

    if pit_calcs:
        st.markdown("### PIT calculations")
        for c in pit_calcs:
            summary = c.get("summary") or {}
            with st.container(border=True):
                cols = st.columns([3, 3, 2, 1])
                with cols[0]:
                    st.markdown(f"**PIT – {c.get('assessmentYear')}**")
                    st.caption(f"ID: {c.get('id')}")
                    st.caption(f"Tag: {employment_tag}")
                with cols[1]:
                    total_tax = summary.get("totalTax")
                    if total_tax is not None:
                        st.write(f"Annual tax: ₦{total_tax:,.2f}")
                with cols[2]:
                    eff = summary.get("effectiveRate")
                    if eff is not None:
                        st.write(f"Effective rate: {eff * 100:.2f}%")
                with cols[3]:
                    if st.button("View", key=f"view_pit_{c['id']}"):
                        st.session_state[selected_id_key] = c["id"]

    if paye_calcs:
        st.markdown("### PAYE calculations")
        for c in paye_calcs:
            summary = c.get("summary") or {}
            with st.container(border=True):
                cols = st.columns([3, 3, 2, 1])
                with cols[0]:
                    st.markdown(f"**PAYE – {c.get('assessmentYear')}**")
                    st.caption(f"ID: {c.get('id')}")
                    st.caption(f"Tag: {employment_tag}")
                with cols[1]:
                    exp_month = summary.get("expectedMonthlyPaye")
                    if exp_month is not None:
                        st.write(f"Expected PAYE/mth: ₦{exp_month:,.2f}")
                with cols[2]:
                    direction = summary.get("differenceDirection") or "MATCH"
                    st.write(f"Direction: {direction}")
                with cols[3]:
                    if st.button("View", key=f"view_paye_{c['id']}"):
                        st.session_state[selected_id_key] = c["id"]

    selected_id = st.session_state.get(selected_id_key)

    if selected_id:
        st.markdown("---")
        st.subheader("Selected calculation")

        ok, detail = client.get_calculation(selected_id, auth["access_token"])
        if not ok:
            show_api_error(detail)
            return

        st.caption(f"ID: {selected_id}")
        st.json(detail)

        output = detail.get("output") or {}
        calc_type = detail.get("type")

        with st.expander("Explain this result", expanded=True):
            if calc_type == "PIT":
                explain_pit_output(output)
            elif calc_type == "PAYE":
                explain_paye_output(output)
            else:
                st.info("Explanation is only available for PIT and PAYE calculations.")

        with st.expander("Download this result"):
            render_downloads_for_calc(detail)


# ---------- Page: hustle ----------

def page_hustle():
    st.header("My Hustle")

    if not require_login():
        return

    auth = get_auth_state()
    client = get_client()
    profile = load_profile_if_needed()

    # Load hustles (businesses)
    if "hustles" not in st.session_state:
        ok, data = client.list_hustles(auth["access_token"])
        if ok:
            st.session_state.hustles = data
        else:
            st.session_state.hustles = []
            show_api_error(data)
            return

    hustles = st.session_state.hustles

    st.subheader("Create a new hustle")

    with st.form("create_hustle_form"):
        name = st.text_input("Hustle name (e.g. POS stand, hair business)")
        sector = st.text_input("Sector (optional, e.g. POS, Beauty, Food)")
        description = st.text_area("Short description (optional)", height=60)
        created = st.form_submit_button("Save hustle")

    if created:
        if not name:
            st.error("Hustle name is required.")
        else:
            payload = {
                "name": name,
                "sector": sector or None,
                "description": description or None,
            }
            ok, data = client.create_hustle(payload, auth["access_token"])
            if ok:
                st.success("Hustle created.")
                st.session_state.hustles.insert(0, data)
                hustles = st.session_state.hustles
            else:
                show_api_error(data)

    st.markdown("---")

    if not hustles:
        st.info("You don't have any hustles yet. Create one above.")
        return

    st.subheader("Select hustle")

    hustle_names = [f"{h['name']} ({h.get('sector') or 'General'})" for h in hustles]
    selected_index = st.selectbox(
        "Choose which hustle to work with",
        options=list(range(len(hustles))),
        format_func=lambda i: hustle_names[i],
    )
    selected_hustle = hustles[selected_index]
    hustle_id = selected_hustle["id"]

    st.markdown(f"**Selected hustle:** {selected_hustle['name']}")

    tab_manual, tab_import = st.tabs(["Manual entries", "Import from statement (CSV)"])

    # ---------- Manual entries tab ----------

    with tab_manual:
        st.markdown("### Add an entry manually")

        with st.form("add_tx_form"):
            tx_date = st.date_input("Date", value=date.today())
            tx_type = st.selectbox("Type", options=["INCOME", "EXPENSE"], index=0)
            category = st.text_input("Category (e.g. SALES, STOCK, FUEL, DATA)")
            amount = st.number_input(
                "Amount (₦)",
                min_value=0.0,
                value=0.0,
                step=1000.0,
                format="%.2f",
            )
            note = st.text_input("Note (optional)")
            added = st.form_submit_button("Add entry")

        if added:
            if amount <= 0 or not category:
                st.error("Category and a positive amount are required.")
            else:
                tx_payload = {
                    "date": tx_date.isoformat(),
                    "type": tx_type,
                    "category": category,
                    "amount": float(amount),
                    "note": note or None,
                }
                ok, data = client.add_hustle_transaction(hustle_id, tx_payload, auth["access_token"])
                if ok:
                    st.success("Entry added.")
                else:
                    show_api_error(data)

        st.markdown("### Recent entries")

        ok, txs = client.list_hustle_transactions(hustle_id, auth["access_token"], limit=50)
        if ok and txs:
            tx_rows = []
            for t in txs:
                tx_rows.append({
                    "Date": t.get("date"),
                    "Type": t.get("type"),
                    "Category": t.get("category"),
                    "Amount (₦)": float(t.get("amount") or 0),
                    "Note": t.get("note") or "",
                })
            st.dataframe(tx_rows, use_container_width=True)
        elif ok:
            st.info("No entries yet for this hustle.")
        else:
            show_api_error(txs)

    # ---------- Import from statement tab ----------

    with tab_import:
        st.markdown(
            "Upload a **CSV** or **PDF** bank statement.\n\n"
            "- CSV: should have columns `date`, `description`, `debit`, `credit`.\n"
            "- PDF: currently tuned for GTBank-style statements (Trans Date, Reference, Value Date, Debit, Credit, Balance, Remarks)."
        )
        uploaded_file = st.file_uploader(
            "Upload statement",
            type=["csv", "pdf"],
            key="hustle_statement_uploader",
        )

        statement = None

        if uploaded_file is not None:
            filename = uploaded_file.name
            file_bytes = uploaded_file.read()

            # Build preview_rows and backend_rows depending on file type
            if filename.lower().endswith(".csv"):
                content = file_bytes.decode("utf-8", errors="ignore")
                reader = csv.DictReader(io.StringIO(content))

                required_cols = {"date", "description", "debit", "credit"}
                missing = required_cols - set(reader.fieldnames or [])
                if missing:
                    st.error(
                        f"CSV is missing required columns: {', '.join(sorted(missing))}. "
                        "Make sure the header row includes: date, description, debit, credit."
                    )
                    return

                preview_rows = []
                backend_rows = []

                for row in reader:
                    date_str = (row.get("date") or "").strip()
                    desc = (row.get("description") or "").strip()
                    debit_str = (row.get("debit") or "").replace(",", "").strip()
                    credit_str = (row.get("credit") or "").replace(",", "").strip()

                    if not date_str or not desc:
                        continue

                    try:
                        debit = float(debit_str) if debit_str not in ("", None) else 0.0
                    except ValueError:
                        debit = 0.0
                    try:
                        credit = float(credit_str) if credit_str not in ("", None) else 0.0
                    except ValueError:
                        credit = 0.0

                    if credit > 0:
                        direction = "INCOME"
                        amount = credit
                    elif debit > 0:
                        direction = "EXPENSE"
                        amount = debit
                    else:
                        continue

                    backend_rows.append(
                        {
                            "date": date_str,
                            "description": desc,
                            "amount": amount,
                            "direction": direction,
                            "reference": None,
                            "counterparty": None,
                        }
                    )
                    preview_rows.append(
                        {
                            "date": date_str,
                            "description": desc,
                            "debit": debit,
                            "credit": credit,
                            "mapped_direction": direction,
                            "mapped_amount": amount,
                        }
                    )

            elif filename.lower().endswith(".pdf"):
                try:
                    preview_rows, backend_rows = parse_gtbank_pdf_to_rows(file_bytes)
                except Exception as e:
                    st.error(f"Could not parse PDF statement: {e}")
                    return

            else:
                st.error("Unsupported file type. Please upload a CSV or PDF.")
                return

            if not backend_rows:
                st.warning("No usable rows found in this statement.")
                return

            st.subheader("Preview of interpreted rows")
            st.dataframe(preview_rows[:100], use_container_width=True)

            if st.button("Import and auto-categorise this statement"):
                payload = {
                    "source": "PDF upload" if filename.lower().endswith(".pdf") else "CSV upload",
                    "fileName": filename,
                    "rows": backend_rows,
                }
                ok, statement = client.import_statement(
                    hustle_id,
                    payload,
                    auth["access_token"],
                )
                if ok:
                    st.success(
                        f"Statement imported with {len(statement.get('rows') or [])} rows."
                    )
                    st.session_state["last_statement_import"] = statement
                else:
                    show_api_error(statement)

        # If we have a statement (either just imported or from session), show review/editor
        if "last_statement_import" in st.session_state:
            statement = st.session_state["last_statement_import"]

            st.markdown("### Review & confirm rows to import into this hustle")

            rows = statement.get("rows") or []
            if not rows:
                st.info("No rows available in this imported statement.")
            else:
                # Build editable dataframe
                data_for_editor = []
                for r in rows:
                    amount = 0.0
                    try:
                        amount = float(r.get("amountRaw") or 0)
                    except Exception:
                        amount = 0.0

                    direction = r.get("directionSuggested") or "INCOME"
                    suggested_category = r.get("categorySuggested") or "MISC"
                    # Ensure category is in our allowed list
                    if suggested_category not in CATEGORY_OPTIONS:
                        category = "MISC"
                    else:
                        category = suggested_category

                    data_for_editor.append(
                        {
                            "import": True,
                            "id": r.get("id"),
                            "date": r.get("dateRaw"),
                            "description": r.get("descriptionRaw"),
                            "amount": amount,
                            "direction": direction,
                            "category": category,
                            "source": r.get("source"),
                            "confidence": r.get("confidence"),
                        }
                    )

                df = pd.DataFrame(data_for_editor)

                edited_df = st.data_editor(
                    df,
                    use_container_width=True,
                    num_rows="fixed",
                    column_config={
                        "import": st.column_config.CheckboxColumn(
                            "Import?", help="Tick to import this row into your hustle"
                        ),
                        "direction": st.column_config.SelectboxColumn(
                            "Type",
                            options=["INCOME", "EXPENSE"],
                        ),
                        "category": st.column_config.SelectboxColumn(
                            "Category",
                            options=CATEGORY_OPTIONS,
                            help="Choose the category for this transaction",
                        ),
                        "amount": st.column_config.NumberColumn("Amount (₦)"),
                        "confidence": st.column_config.NumberColumn("Confidence", format="%.2f"),
                    },
                    hide_index=True,
                )

                if st.button("Save selected rows into my hustle"):
                    items = []
                    for _, row in edited_df.iterrows():
                        if not row.get("import"):
                            continue
                        tx_id = row.get("id")
                        final_type = row.get("direction")
                        final_category = row.get("category")
                        if not tx_id or not final_type or not final_category:
                            continue
                        items.append(
                            {
                                "importedTransactionId": str(tx_id),
                                "finalType": str(final_type),
                                "finalCategory": str(final_category),
                                "note": None,
                            }
                        )

                    if not items:
                        st.warning("No rows selected for import.")
                    else:
                        payload = {"items": items}
                        ok, result = client.confirm_statement(
                            hustle_id,
                            statement.get("id"),
                            payload,
                            auth["access_token"],
                        )
                        if ok:
                            st.success(
                                f"Imported {result.get('createdCount', 0)} transactions into your hustle."
                            )
                        else:
                            show_api_error(result)


    # ---------- Hustle-level tax estimate (same as before) ----------

    st.markdown("### Estimate tax from this hustle")

    default_annual_rent = float(profile.get("defaultAnnualRent") or 0.0) if profile else 0.0
    default_pension_rate = float(profile.get("defaultPensionRate") or 8.0) if profile else 8.0
    default_nhf_rate = float(profile.get("defaultNhfRate") or 0.0) if profile else 0.0

    with st.form("hustle_summary_form"):
        assessment_year = st.number_input(
            "Assessment year",
            min_value=2000,
            max_value=2100,
            value=2026,
            step=1,
        )
        period_months = st.number_input(
            "Months covered by the entries so far",
            min_value=1,
            max_value=24,
            value=12,
            step=1,
        )
        annual_rent = st.number_input(
            "Annual rent to apply for this hustle (₦)",
            min_value=0.0,
            value=default_annual_rent,
            step=50000.0,
            format="%.2f",
        )
        pension_rate = st.number_input(
            "Pension rate on profit (%)",
            min_value=0.0,
            max_value=30.0,
            value=default_pension_rate,
            step=0.5,
        )
        nhf_rate = st.number_input(
            "NHF rate on profit (%) (optional)",
            min_value=0.0,
            max_value=20.0,
            value=default_nhf_rate,
            step=0.5,
        )
        run_summary = st.form_submit_button("Estimate tax from my hustle entries")

    if run_summary:
        params = {
            "assessmentYear": int(assessment_year),
            "periodMonths": int(period_months),
            "annualRent": float(annual_rent),
            "pensionRate": float(pension_rate),
            "nhfRate": float(nhf_rate),
        }
        ok, summary = client.hustle_summary(hustle_id, auth["access_token"], params)
        if ok:
            total_income = summary.get("totalIncome", 0)
            total_expenses = summary.get("totalExpenses", 0)
            net_profit = summary.get("netProfit", 0)
            tax = summary.get("tax") or {}
            total_tax = tax.get("totalTax", 0)
            effective_rate = tax.get("effectiveRate", 0)

            st.subheader("Hustle summary")

            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Total income (₦)", f"{total_income:,.2f}")
            with col_b:
                st.metric("Total expenses (₦)", f"{total_expenses:,.2f}")
            with col_c:
                st.metric("Net profit (₦)", f"{net_profit:,.2f}")

            st.subheader("Estimated tax on this hustle")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Estimated annual tax (₦)", f"{total_tax:,.2f}")
            with col2:
                st.metric("Effective tax rate on profit", f"{effective_rate * 100:.2f}%")
            with col3:
                monthly_tax = total_tax / 12 if total_tax else 0
                st.metric("Rough tax per month (₦)", f"{monthly_tax:,.2f}")

            with st.expander("Tax details from engine"):
                st.json(tax)
        else:
            show_api_error(summary)



# ---------- Main app ----------

def main():
    st.set_page_config(
        page_title="TaxMate Nigeria",
        page_icon=None,
        layout="centered",
    )

    st.sidebar.title("TaxMate Nigeria")

    page = st.sidebar.radio(
        "Go to",
        [
            "Quick Tax Check",
            "Self-Employed Quick Check",
            "My Hustle",
            "PIT Calculator",
            "PAYE Checker",
            "My Tax History",
            "Profile & Defaults",
            "Account",
        ],
    )

    if page == "Quick Tax Check":
        page_quick_pit()
    elif page == "Self-Employed Quick Check":
        page_self_employed_quick()
    elif page == "My Hustle":
        page_hustle()
    elif page == "PIT Calculator":
        page_pit()
    elif page == "PAYE Checker":
        page_paye()
    elif page == "My Tax History":
        page_history()
    elif page == "Profile & Defaults":
        page_profile()
    elif page == "Account":
        page_account()


if __name__ == "__main__":
    main()
