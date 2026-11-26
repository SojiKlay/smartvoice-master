"""Admin-only manual data management for customers and warranty registrations."""

import pandas as pd
import streamlit as st

st.set_page_config(page_title="SmartVoice — เพิ่ม/แก้ไขข้อมูลลูกค้า", layout="wide")

from datetime import date

from smartvoice import customer_entry, db, file_manager, labels
from smartvoice.auth import PAGE_DATA_ENTRY
from smartvoice.ui_helpers import init_page, render_proof

# Admin only (see smartvoice.auth.ROLE_PERMISSIONS).
current_user, current_role = init_page(PAGE_DATA_ENTRY)

st.title("ข้อมูลลูกค้า & ทะเบียนรับประกัน")
st.html('<style>[data-testid="stCaptionContainer"] p { color: var(--st-text-color, inherit); font-size: 0.95rem; }</style>')
st.caption("เพิ่ม / แก้ไข / ลบ ข้อมูลลูกค้าและทะเบียนรับประกัน — ช่องที่มี * จำเป็นต้องระบุ ช่องอื่นเว้นว่างหรือใช้ค่าเริ่มต้นได้")

_OTHER = "อื่นๆ"
_NONE = "—"
_FLASH_KEY = "_data_entry_flash"
_PHONE_HELP = (
    "เบอร์โทรไม่บังคับ หากกรอก ต้องขึ้นต้นด้วย 0 มี 9–10 หลัก และไม่ซ้ำกับลูกค้ารายอื่น "
    "เมื่อเบอร์ในสายโทรศัพท์ตรงกัน ระบบจะเชื่อมสายนั้นกับประวัติลูกค้าโดยอัตโนมัติ"
)
_REGISTRATION_HELP = "ใช้เลขทะเบียนที่ไม่ซ้ำ อย่างน้อย 3 ตัวอักษร ใช้ตัวอักษรอังกฤษ ตัวเลข หรือ . _ - / ได้"

# Saving reruns the page so the pickers and tables pick up the change, which
# would otherwise wipe the success message before anyone reads it.
_flash = st.session_state.pop(_FLASH_KEY, None)
if _flash:
    st.success(_flash)


def _option_label(value: str) -> str:
    return "ไม่ระบุ" if value == _NONE else value


def _flash_and_rerun(message: str):
    st.session_state[_FLASH_KEY] = message
    st.rerun()


def _as_date(value) -> date | None:
    """Parse an ISO date string from the DB into a date for st.date_input."""
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _pick_with_other(label: str, options, key: str, current: str | None = None):
    """Selectbox with an 'อื่นๆ' escape hatch that reveals a free-text input."""
    choices = (_NONE, *options)
    if current in options:
        index = choices.index(current)
    elif current:
        index = choices.index(_OTHER) if _OTHER in choices else 0
    else:
        index = 0

    choice = st.selectbox(label, choices, index=index, key=key, format_func=_option_label, help="เลือกจากรายการ หรือเลือก อื่นๆ เพื่อพิมพ์เอง")
    if choice == _OTHER:
        typed = st.text_input(
            f"{label} (ระบุเอง)",
            value="" if current in options else (current or ""),
            key=f"{key}_other",
            placeholder=f"พิมพ์{label}ตามเอกสาร",
        )
        return typed.strip() or None
    return None if choice == _NONE else choice


def _customer_label(c: dict) -> str:
    return f"{c['first_name']} {c['last_name']} ({c['phone'] or '-'}) · id={c['id']}"


def _customer_fields(customer: dict) -> dict:
    fields = {}

    def text_field(column, key, label, example, default=""):
        fields[key] = column.text_input(label, value=customer.get(key) or default, placeholder=example)

    st.markdown("**ข้อมูลส่วนบุคคล**")
    st.caption("ต้องกรอกชื่อและนามสกุลในช่องที่มี * ส่วนชื่อเล่น เพศ และวันเกิดเว้นว่างได้")
    left, right = st.columns(2)
    text_field(left, "first_name", "ชื่อ *", "เช่น สมชาย")
    text_field(right, "last_name", "นามสกุล *", "เช่น ใจดี")
    text_field(left, "nick_name", "ชื่อเล่น", "เช่น นิด")
    genders = (_NONE, *customer_entry.GENDERS)
    gender_labels = {_NONE: "ไม่ระบุ", "MALE": "ชาย", "FEMALE": "หญิง", "OTHER": "อื่น ๆ"}
    gender = right.selectbox(
        "เพศ", genders, index=genders.index(customer["gender"]) if customer.get("gender") in genders else 0,
        format_func=lambda value: gender_labels.get(value, value),
    )
    fields["gender"] = None if gender == _NONE else gender
    fields["date_of_birth"] = left.date_input(
        "วันเกิด", value=_as_date(customer.get("date_of_birth")), min_value=date(1920, 1, 1),
        max_value=date.today(), format="DD/MM/YYYY",
    )
    left.caption("เลือกวันเกิดตั้งแต่ 1 มกราคม ค.ศ. 1920 ถึงวันนี้")

    st.markdown("**ข้อมูลติดต่อ (ไม่บังคับ)**")
    left, right = st.columns(2)
    fields["phone"] = left.text_input(
        "เบอร์โทร", value=customer.get("phone") or "", placeholder="เช่น 0812345678", help=_PHONE_HELP,
    )
    left.caption(_PHONE_HELP)
    text_field(right, "email", "อีเมล", "เช่น somchai@example.com")
    channels = (_NONE, *customer_entry.CHANNELS)
    channel = customer.get("channel")
    if channel and channel not in channels:
        channels = (*channels, channel)
    selected_channel = right.selectbox("แบรนด์ที่ลูกค้าติดต่อ", channels, index=channels.index(channel) if channel else 0, format_func=_option_label)
    fields["channel"] = None if selected_channel == _NONE else selected_channel

    st.markdown("**ที่อยู่ (ไม่บังคับ)**")
    fields["address"] = st.text_area(
        "ที่อยู่", value=customer.get("address") or "", placeholder="เช่น 123/45 ซอย 2 ถนนพหลโยธิน", height=100,
    )
    left, right = st.columns(2)
    text_field(left, "subdistrict", "แขวง/ตำบล", "เช่น ลาดยาว")
    text_field(right, "district", "เขต/อำเภอ", "เช่น จตุจักร")
    text_field(left, "city_province", "จังหวัด", "เช่น กรุงเทพมหานคร")
    text_field(right, "postcode", "รหัสไปรษณีย์", "เช่น 10900")
    text_field(left, "country", "ประเทศ", "เช่น Thailand", default="Thailand")
    return fields


def _warranty_editor(customers: dict, warranty: dict) -> None:
    wid = warranty.get("id")
    editing = wid is not None
    suffix = wid if editing else "new"
    prefix = f"_warranty_{suffix}_"
    fields = {}

    def text_field(column, key, label, example, guidance=None):
        fields[key] = column.text_input(
            label, value=warranty.get(key) or "", placeholder=f"เช่น {example}", key=prefix + key,
            help=_REGISTRATION_HELP if key == "registration_no" else None,
        )
        if guidance:
            column.caption(f"{guidance} ตัวอย่าง {example}")

    def pick(label, key, options):
        fields[key] = _pick_with_other(label, options, prefix + key, warranty.get(key))

    st.markdown("**ข้อมูลเจ้าของทะเบียน**")
    st.caption("ต้องระบุสองช่องที่มี * คือเจ้าของทะเบียนและเลขทะเบียนรับประกัน ช่องอื่นเว้นว่างหรือใช้ค่าเริ่มต้นได้")
    owners = list(customers)
    owner = next((name for name in owners if customers[name] == warranty.get("customer_id")), None)
    selected = st.selectbox("ลูกค้าเจ้าของทะเบียน *", owners, index=owners.index(owner) if owner else None, placeholder="กรุณาเลือกเจ้าของทะเบียน", key=prefix + "owner")
    fields["customer_id"] = customers.get(selected)
    text_field(st, "registration_no", "เลขทะเบียนรับประกัน *", "REG-001",
               f"Registration No. คือเลขของรายการทะเบียนนี้ {_REGISTRATION_HELP}")

    st.markdown("**ข้อมูลสินค้า (ไม่บังคับ)**")
    left, right = st.columns(2)
    with left:
        pick("แบรนด์", "brand", customer_entry.BRANDS)
        pick("หมวดหมู่", "category", customer_entry.CATEGORIES)
    text_field(right, "model", "รุ่น", "Natura Latex")
    text_field(right, "size", "ขนาด", "5 ฟุต")
    text_field(left, "serial_no", "หมายเลขประจำสินค้า (Serial No.)", "SN-001",
               "กรอกหมายเลขประจำชิ้นที่ระบุว่า Serial No. บนสินค้าหรือเอกสาร")
    text_field(right, "label_no", "เลขบนป้ายสินค้า (Label No.)", "LB-001",
               "กรอกเลขที่ระบุว่า Label No. บนป้ายสินค้าหรือเอกสาร")
    text_field(left, "sku", "รหัสสินค้า (SKU)", "SKU-001", "กรอกรหัสที่ระบุว่า SKU ในรายการสินค้า")

    st.markdown("**เอกสารอ้างอิง (ไม่บังคับ)**")
    left, right = st.columns(2)
    text_field(left, "certificate_no", "เลขที่ใบรับประกัน (Certificate No.)", "CERT-001",
               "คัดลอกเลขที่ใบรับประกันจากเอกสารที่ได้รับ")
    text_field(right, "order_number", "เลขที่คำสั่งซื้อ (Order Number)", "ORD-001",
               "กรอกเลขคำสั่งซื้อที่ร้านค้าหรือช่องทางออนไลน์แสดงให้ผู้ซื้อ")
    text_field(left, "so_number", "เลขที่ SO", "SO-001", "กรอกเลขที่ใบสั่งขาย (Sales Order) หากมีเอกสารอ้างอิง")
    text_field(right, "ref_id", "เลขอ้างอิงทะเบียน (Ref Id)", "REF-001",
               "กรอกค่าจากช่อง Ref Id ในข้อมูลต้นทาง หากไม่มีให้เว้นว่าง")
    with left:
        pick("ช่องทาง (แบรนด์ร้าน)", "channel", customer_entry.CHANNELS)
    with right:
        pick("ช่องทางซื้อ", "purchase_channel", customer_entry.PURCHASE_CHANNELS)
    if editing:
        st.markdown("**หลักฐานการซื้อปัจจุบัน**")
        render_proof(warranty.get("proof_path"), key=prefix + "proof_view")
    proof = st.file_uploader(
        "แนบหลักฐานการซื้อใหม่ (แทนที่ไฟล์เดิม)" if editing else "แนบหลักฐานการซื้อ เช่น ใบเสร็จหรือสลิป",
        type=["jpg", "jpeg", "png", "webp", "pdf"], key=prefix + "proof", max_upload_size=file_manager.MAX_PROOF_SIZE_MB,
    )
    st.caption(f"รองรับ JPG/JPEG, PNG, WEBP และ PDF ขนาดไม่เกิน {file_manager.MAX_PROOF_SIZE_MB} MB ต่อไฟล์")

    st.markdown("**เงื่อนไขการรับประกัน (ไม่บังคับ)**")
    st.caption("วันที่ทุกช่องใช้วัน/เดือน/ปี ค.ศ. (DD/MM/YYYY)")
    left, right = st.columns(2)
    fields["date_of_purchase"] = left.date_input(
        "วันที่ซื้อ", value=_as_date(warranty.get("date_of_purchase")) if editing else date.today(),
        format="DD/MM/YYYY", key=prefix + "date_of_purchase",
    )
    fields["date_of_delivery"] = right.date_input(
        "วันที่ส่งมอบ", value=_as_date(warranty.get("date_of_delivery")), format="DD/MM/YYYY", key=prefix + "date_of_delivery",
    )
    fields["warranty_period_months"] = left.number_input(
        "ระยะเวลารับประกัน (เดือน)", min_value=0, max_value=600, step=12,
        value=int(warranty.get("warranty_period_months", 120) or 0), key=prefix + "months",
    )
    years, months = divmod(fields["warranty_period_months"], 12)
    left.markdown(f"**{fields['warranty_period_months']} เดือน** เท่ากับ {years} ปี {months} เดือน")
    left.caption("ระบุ 0–600 เดือน เช่น 12 เดือน = 1 ปี และ 120 เดือน = 10 ปี "
                 "ทะเบียนใหม่เริ่มที่ 120 เดือน โปรดตรวจวันที่ซื้อและจำนวนเดือนให้ตรงกับเงื่อนไขก่อนบันทึก")
    auto = st.checkbox("คำนวณวันหมดประกันอัตโนมัติ", value=not editing, key=prefix + "auto")
    calculated = customer_entry.compute_expiry_date(fields["date_of_purchase"], fields["warranty_period_months"])
    st.caption("ระบบนับจากวันที่ซื้อ บวกจำนวนเดือนรับประกัน หากเดือนปลายทางไม่มีวันที่ตรงกัน จะใช้วันสุดท้ายของเดือน")
    if auto:
        if calculated:
            st.success(f"วันหมดประกันที่คำนวณได้ **{date.fromisoformat(calculated):%d/%m/%Y}** (ค.ศ.)")
        else:
            st.info("หากต้องการคำนวณ ให้ระบุวันที่ซื้อและจำนวนเดือนมากกว่า 0")
    fields["expiry_date"] = None
    if not auto:
        fields["expiry_date"] = st.date_input(
            "วันหมดประกัน", value=_as_date(warranty.get("expiry_date")), format="DD/MM/YYYY", key=prefix + "expiry",
        )
        st.caption("กรอกวันที่ตามเอกสาร หากเว้นว่าง ระบบจะใช้วันที่คำนวณได้จากวันที่ซื้อและระยะเวลารับประกัน")
    fields["remark"] = st.text_area(
        "หมายเหตุ", value=warranty.get("remark") or "", placeholder="เช่น รายละเอียดเพิ่มเติมเกี่ยวกับการรับประกัน",
        height=80, key=prefix + "remark",
    )
    if st.button("บันทึกการแก้ไข" if editing else "บันทึกทะเบียนรับประกัน", type="primary", key=f"_save_w_{suffix}", use_container_width=True):
        fields["proof_path"] = warranty.get("proof_path")
        if proof is not None:
            try:
                fields["proof_path"], error = file_manager.save_proof_file(proof.getvalue())
            except OSError:
                st.error("บันทึกหลักฐานการซื้อไม่ได้ กรุณาลองบันทึกอีกครั้ง หากยังพบปัญหา ให้แจ้งผู้ดูแลระบบตรวจพื้นที่จัดเก็บไฟล์")
                return
            if error:
                st.error(f"หลักฐานการซื้อ — {error} กรุณาเลือกไฟล์ที่รองรับอีกครั้ง หรือนำไฟล์แนบออกแล้วบันทึก")
                return
        reg = fields["registration_no"].strip()
        if editing:
            error = customer_entry.update_warranty(wid, actor=current_user, actor_role=current_role, **fields)
            success = f"บันทึกการแก้ไขทะเบียน **{reg}** เรียบร้อยแล้ว"
        else:
            new_id, error = customer_entry.create_warranty(actor=current_user, actor_role=current_role, **fields)
            success = f"บันทึกทะเบียน **{reg}** เรียบร้อยแล้ว (id={new_id})"
        if error:
            st.error(error)
        else:
            _flash_and_rerun(success)


def _recent_table(rows: list[dict], columns: dict, empty_message: str):
    if not rows:
        st.info(empty_message)
        return
    st.dataframe(
        pd.DataFrame([{label: fn(r) for label, fn in columns.items()} for r in rows]),
        width="stretch",
        hide_index=True,
    )


tab_customer, tab_warranty, tab_hidden = st.tabs(
    ["ลูกค้า", "ทะเบียนรับประกัน", "รายการที่ซ่อนไว้"]
)

# ─────────────────────────────────────────
# TAB 1 — CUSTOMERS
# ─────────────────────────────────────────
with tab_customer:
    customers = db.get_all_customers()

    with st.expander("เพิ่มลูกค้าใหม่", expanded=not customers):
        with st.form("_add_customer_form"):
            fields = _customer_fields({})
            customer_submitted = st.form_submit_button("บันทึกลูกค้า", type="primary", use_container_width=True)

        if customer_submitted:
            new_id, error = customer_entry.create_customer(
                actor=current_user,
                actor_role=current_role,
                **fields,
            )
            if error:
                st.error(error)
            else:
                _flash_and_rerun(
                    f"บันทึกลูกค้า **{fields['first_name'].strip()} {fields['last_name'].strip()}** เรียบร้อยแล้ว (id={new_id})"
                )

    st.divider()
    st.subheader("แก้ไข / ลบ ลูกค้า")

    if not customers:
        st.info("ยังไม่มีข้อมูลลูกค้าในระบบ")
    else:
        search = st.text_input(
            "ค้นหาลูกค้าที่ต้องการแก้ไข", placeholder="ชื่อ หรือ เบอร์โทร", key="_edit_c_search"
        )
        matches = customers
        if search:
            q = search.lower()
            matches = [
                c for c in customers
                if q in f"{c['first_name']}{c['last_name']}{c['phone'] or ''}".lower()
            ]

        if not matches:
            st.warning("ไม่พบลูกค้าที่ตรงกับคำค้นหา")
        else:
            picked = st.selectbox(
                "เลือกลูกค้า", matches, format_func=_customer_label, key="_edit_c_pick"
            )
            cid = picked["id"]
            deps = db.count_customer_dependencies(cid)
            dep_text = customer_entry.describe_dependencies(deps)
            st.caption(f"ข้อมูลที่ผูกอยู่: {dep_text or 'ไม่มี'}")

            with st.form(f"_edit_customer_form_{cid}"):
                edited_fields = _customer_fields(picked)

                edit_submitted = st.form_submit_button("บันทึกการแก้ไข", type="primary", use_container_width=True)

            if edit_submitted:
                error = customer_entry.update_customer(
                    cid,
                    actor=current_user,
                    actor_role=current_role,
                    **edited_fields,
                )
                if error:
                    st.error(error)
                else:
                    _flash_and_rerun(
                        f"บันทึกการแก้ไข **{edited_fields['first_name'].strip()} {edited_fields['last_name'].strip()}** เรียบร้อยแล้ว"
                    )

            st.markdown("**ลบลูกค้า (ซ่อนไว้ — กู้คืนได้)**")
            st.caption(
                "ข้อมูลจะไม่ถูกลบออกจากฐานข้อมูล แต่จะถูกซ่อนพร้อมทะเบียนรับประกันของลูกค้ารายนี้ "
                "และบันทึกลงประวัติว่าใครซ่อนเมื่อไหร่ — กู้คืนได้ที่แท็บ “รายการที่ซ่อนไว้” "
                "ส่วนสาย เคส และการเชื่อมสายยังอยู่ครบ"
            )
            confirm_hide = st.checkbox(
                f"ยืนยันซ่อน `{picked['first_name']} {picked['last_name']}`",
                key=f"_confirm_delete_customer_{cid}",
            )
            if st.button("ลบลูกค้ารายนี้", key=f"_delete_customer_{cid}", disabled=not confirm_hide):
                result, error = customer_entry.hide_customer(
                    cid, actor=current_user, actor_role=current_role
                )
                if error:
                    st.error(error)
                else:
                    hidden_w = result.get("warranties") or 0
                    _flash_and_rerun(
                        f"ซ่อนลูกค้าเรียบร้อยแล้ว"
                        + (f" (พร้อมทะเบียนรับประกัน {hidden_w} รายการ)" if hidden_w else "")
                    )

    st.divider()
    st.subheader("ลูกค้าที่เพิ่มล่าสุด")
    _recent_table(
        sorted(customers, key=lambda c: (c["created_at"], c["id"]), reverse=True)[:10],
        {
            "id": lambda c: c["id"],
            "ชื่อ": lambda c: f"{c['first_name']} {c['last_name']}",
            "เบอร์": lambda c: c["phone"] or "—",
            "อีเมล": lambda c: c["email"] or "—",
            "จังหวัด": lambda c: c["city_province"] or "—",
            "เพิ่มเมื่อ": lambda c: labels.thai_time(c["created_at"]),
        },
        "ยังไม่มีข้อมูลลูกค้าในระบบ",
    )

# ─────────────────────────────────────────
# TAB 2 — WARRANTY REGISTRATIONS
# ─────────────────────────────────────────
with tab_warranty:
    customers = db.get_all_customers()
    warranties = db.get_all_warranties()

    if not customers:
        st.warning("ต้องมีลูกค้าในระบบก่อน — เพิ่มลูกค้าที่แท็บ “ลูกค้า” ก่อนบันทึกทะเบียนรับประกัน")
    else:
        cust_map = {
            _customer_label(c): c["id"]
            for c in sorted(customers, key=lambda c: (c["last_name"], c["first_name"]))
        }

        with st.expander("เพิ่มทะเบียนรับประกันใหม่", expanded=not warranties):
            _warranty_editor(cust_map, {})

        st.divider()
        st.subheader("แก้ไข / ลบ ทะเบียนรับประกัน")

        if not warranties:
            st.info("ยังไม่มีทะเบียนรับประกันในระบบ")
        else:
            w_search = st.text_input(
                "ค้นหาทะเบียนที่ต้องการแก้ไข",
                placeholder="เลขทะเบียน, Serial, แบรนด์, รุ่น หรือชื่อลูกค้า",
                key="_edit_w_search",
            )
            w_matches = warranties
            if w_search:
                q = w_search.lower()
                w_matches = [
                    w for w in warranties
                    if q in " ".join(
                        str(w.get(col) or "")
                        for col in ("registration_no", "serial_no", "brand", "model",
                                    "first_name", "last_name", "phone")
                    ).lower()
                ]

            if not w_matches:
                st.warning("ไม่พบทะเบียนที่ตรงกับคำค้นหา")
            else:
                picked_w = st.selectbox(
                    "เลือกทะเบียน",
                    w_matches,
                    format_func=lambda w: (
                        f"{w['registration_no']} — {w['brand'] or '-'} {w['model'] or ''} "
                        f"({w.get('first_name') or '-'} {w.get('last_name') or ''})"
                    ),
                    key="_edit_w_pick",
                )
                wid = picked_w["id"]
                _warranty_editor(cust_map, picked_w)

                status_now = picked_w.get("status") or "active"
                st.markdown(f"**สถานะทะเบียน: {labels.warranty_status(status_now)}**")
                if status_now == "cancelled":
                    st.caption(
                        f"ยกเลิกโดย {picked_w.get('cancelled_by') or '-'} "
                        f"เมื่อ {labels.thai_time(picked_w.get('cancelled_at'))}"
                    )
                st.caption(
                    "ยกเลิก (Cancel) = ทะเบียนยังแสดงอยู่พร้อมสถานะยกเลิก เช่น ลูกค้าคืนสินค้า "
                    "— ต่างจากการลบ ซึ่งซ่อนทะเบียนออกจากทุกหน้า"
                )
                target_status = "active" if status_now == "cancelled" else "cancelled"
                confirm_status = st.checkbox(
                    f"ยืนยัน{'เปิดใช้ทะเบียนนี้อีกครั้ง' if target_status == 'active' else 'ยกเลิกทะเบียนนี้'}",
                    key=f"_confirm_status_w_{wid}",
                )
                if st.button(
                    "เปิดใช้อีกครั้ง (Active)" if target_status == "active" else "ยกเลิกทะเบียน (Cancel)",
                    key=f"_status_w_{wid}",
                    disabled=not confirm_status,
                ):
                    error = customer_entry.set_warranty_status(
                        wid, target_status, actor=current_user, actor_role=current_role
                    )
                    if error:
                        st.error(error)
                    else:
                        _flash_and_rerun(
                            f"เปลี่ยนสถานะทะเบียน `{picked_w['registration_no']}` เป็น "
                            f"{labels.warranty_status(target_status)} แล้ว"
                        )

                st.markdown("**ลบทะเบียนรับประกัน (ซ่อนไว้ — กู้คืนได้)**")
                st.caption(
                    "แถวนี้จะยังอยู่ในฐานข้อมูล แต่ถูกซ่อนจากทุกหน้า และบันทึกลงประวัติว่าใครซ่อน"
                )
                confirm_w = st.checkbox(
                    f"ยืนยันซ่อนทะเบียน `{picked_w['registration_no']}`",
                    key=f"_confirm_delete_w_{wid}",
                )
                if st.button("ลบทะเบียนนี้", key=f"_delete_w_{wid}", disabled=not confirm_w):
                    error = customer_entry.hide_warranty(
                        wid, actor=current_user, actor_role=current_role
                    )
                    if error:
                        st.error(error)
                    else:
                        _flash_and_rerun(f"ซ่อนทะเบียน `{picked_w['registration_no']}` แล้ว")

        st.divider()
        st.subheader("ทะเบียนที่เพิ่มล่าสุด")
        _recent_table(
            sorted(warranties, key=lambda w: (w["created_at"], w["id"]), reverse=True)[:10],
            {
                "เลขทะเบียน": lambda w: w["registration_no"],
                "ลูกค้า": lambda w: f"{w.get('first_name') or '—'} {w.get('last_name') or ''}".strip(),
                "แบรนด์": lambda w: w["brand"] or "—",
                "รุ่น": lambda w: w["model"] or "—",
                "ขนาด": lambda w: w["size"] or "—",
                "วันที่ซื้อ": lambda w: w["date_of_purchase"] or "—",
                "หมดประกัน": lambda w: w["expiry_date"] or "—",
                "เพิ่มเมื่อ": lambda w: labels.thai_time(w["created_at"]),
            },
            "ยังไม่มีทะเบียนรับประกันในระบบ",
        )

# ─────────────────────────────────────────
# TAB 3 — HIDDEN ROWS (restore)
# ─────────────────────────────────────────
with tab_hidden:
    st.caption(
        "รายการที่ถูก \"ลบ\" จะไม่หายไปจากฐานข้อมูล — ถูกซ่อนไว้ที่นี่และกู้คืนได้ทุกเมื่อ"
    )

    hidden_customers = db.get_deleted_customers()
    hidden_warranties = db.get_deleted_warranties()

    st.subheader(f"ลูกค้าที่ซ่อนไว้ ({len(hidden_customers)})")
    if not hidden_customers:
        st.info("ไม่มีลูกค้าที่ถูกซ่อนไว้")
    for row in hidden_customers:
        cols = st.columns([4, 2, 2, 1.4])
        cols[0].markdown(
            f"**{row['first_name']} {row['last_name']}** · `{row['phone'] or '-'}` · id={row['id']}"
        )
        cols[1].caption(f"ซ่อนโดย: {row['deleted_by'] or '—'}")
        cols[2].caption(f"เมื่อ: {labels.thai_time(row['deleted_at'])}")
        if cols[3].button("กู้คืน", key=f"_restore_c_{row['id']}", use_container_width=True):
            result, error = customer_entry.restore_customer(
                row["id"], actor=current_user, actor_role=current_role
            )
            if error:
                st.error(error)
            else:
                back = result.get("warranties") or 0
                _flash_and_rerun(
                    f"กู้คืน **{row['first_name']} {row['last_name']}** แล้ว"
                    + (f" (พร้อมทะเบียนรับประกัน {back} รายการ)" if back else "")
                )

    st.divider()
    st.subheader(f"ทะเบียนรับประกันที่ซ่อนไว้ ({len(hidden_warranties)})")
    if not hidden_warranties:
        st.info("ไม่มีทะเบียนรับประกันที่ถูกซ่อนไว้")
    for row in hidden_warranties:
        cols = st.columns([4, 2, 2, 1.4])
        owner = f"{row.get('first_name') or '—'} {row.get('last_name') or ''}".strip()
        cols[0].markdown(
            f"**{row['registration_no']}** · {row['brand'] or '-'} {row['model'] or ''} · {owner}"
        )
        cols[1].caption(f"ซ่อนโดย: {row['deleted_by'] or '—'}")
        cols[2].caption(f"เมื่อ: {labels.thai_time(row['deleted_at'])}")
        if cols[3].button("กู้คืน", key=f"_restore_w_{row['id']}", use_container_width=True):
            error = customer_entry.restore_warranty(
                row["id"], actor=current_user, actor_role=current_role
            )
            if error:
                st.error(error)
            else:
                _flash_and_rerun(f"กู้คืนทะเบียน `{row['registration_no']}` แล้ว")

