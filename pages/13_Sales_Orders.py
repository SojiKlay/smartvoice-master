"""ใบสั่งขาย (SO) — browse sales orders, import them from Excel/CSV, edit one.

Everyone who can see customers can read SOs. Importing, editing, linking and
hiding follow the data-entry permission (Admin), like customer/warranty edits.
"""

from datetime import date

import pandas as pd
import streamlit as st

st.set_page_config(page_title="SmartVoice — ใบสั่งขาย (SO)", layout="wide")

from smartvoice import db, labels, sales_orders
from smartvoice.auth import PAGE_DATA_ENTRY, PAGE_SALES_ORDERS, can_access
from smartvoice.so_view import order_table, render_order
from smartvoice.ui_helpers import TABLE_CLICK_MODES, init_page, picked_row

user, role = init_page(PAGE_SALES_ORDERS)
can_edit = can_access(role, PAGE_DATA_ENTRY)

st.title("ใบสั่งขาย (SO)")
st.html('<style>[data-testid="stCaptionContainer"] p { color: var(--st-text-color, inherit); font-size: 0.95rem; }</style>')
st.caption(
    "ค้นหาใบสั่งขายด้วยเลขที่ SO ชื่อ เบอร์ หรือรหัส/ชื่อสินค้า แล้วคลิกแถวเพื่อเปิดดูทั้งใบ "
    "— SO จะผูกกับลูกค้าในระบบอัตโนมัติจากเบอร์ผู้รับ (หรือเบอร์ผู้ซื้อ)"
)


def _flash(kind: str, message: str) -> None:
    st.session_state["_so_flash"] = (kind, message)


_pending = st.session_state.pop("_so_flash", None)
if _pending:
    getattr(st, _pending[0])(_pending[1])


def _customer_label(c: dict) -> str:
    return f"{c['first_name']} {c['last_name']} ({c.get('phone') or '-'})"


@st.dialog("รายละเอียดใบสั่งขาย", width="large")
def _so_dialog(so_id: int) -> None:
    order = db.get_sales_order(so_id=so_id)
    if not order:
        st.warning("ไม่พบ SO นี้แล้ว — อาจถูกซ่อนไว้")
        return
    render_order(order)
    if not can_edit:
        return

    st.divider()
    customers = db.get_all_customers()
    options = [None] + [c["id"] for c in customers]
    names = {c["id"]: _customer_label(c) for c in customers}
    current = order.get("customer_id")
    picked = st.selectbox(
        "ผูกกับลูกค้าในระบบ",
        options,
        index=options.index(current) if current in options else 0,
        format_func=lambda cid: "ไม่ระบุ (ไม่ผูกกับลูกค้า)" if cid is None else names.get(cid, str(cid)),
        key=f"_so_link_{so_id}",
    )
    link_col, hide_col = st.columns(2)
    if link_col.button("บันทึกการผูกลูกค้า", key=f"_so_link_btn_{so_id}", disabled=picked == current,
                       width="stretch"):
        error = sales_orders.link_customer(so_id, picked, actor=user, actor_role=role)
        _flash("error" if error else "success", error or f"ผูก SO {order['so_number']} กับลูกค้าแล้ว")
        st.rerun()
    with hide_col:
        confirm = st.checkbox("ยืนยันซ่อน SO นี้", key=f"_so_hide_ok_{so_id}")
        if st.button("ซ่อน SO", key=f"_so_hide_{so_id}", disabled=not confirm, width="stretch"):
            error = sales_orders.hide(so_id, actor=user, actor_role=role)
            _flash("error" if error else "success",
                   error or f"ซ่อน SO {order['so_number']} แล้ว — กู้คืนได้ที่แท็บ SO ที่ซ่อนไว้")
            st.rerun()
    st.caption("ต้องการแก้รายละเอียด SO ให้ไปที่แท็บ เพิ่ม/แก้ไข SO")


tab_names = ["รายการ SO"]
if can_edit:
    tab_names += ["นำเข้าจาก Excel / CSV", "เพิ่ม/แก้ไข SO", "SO ที่ซ่อนไว้"]
tabs = st.tabs(tab_names)

# ── รายการ SO ────────────────────────────────────────────────────────────
with tabs[0]:
    total_all = db.count_sales_orders()
    if not total_all:
        st.info(
            "ยังไม่มีใบสั่งขายในระบบ"
            + (" — นำเข้าจากไฟล์ Excel ได้ที่แท็บ นำเข้าจาก Excel / CSV" if can_edit else "")
        )
    else:
        search_col, limit_col = st.columns([3, 1])
        search = search_col.text_input(
            "ค้นหา SO", placeholder="เลขที่ SO, ชื่อผู้ซื้อ/ผู้รับ, เบอร์, เลข PO, รหัสหรือชื่อสินค้า",
            key="_so_search",
        )
        limits = {"200 ล่าสุด": 200, "1,000 ล่าสุด": 1000, "ทั้งหมด": None}
        limit_label = limit_col.selectbox("จำนวนที่แสดง", list(limits), key="_so_limit")
        found = db.count_sales_orders(search=search or None)
        orders = db.list_sales_orders(search=search or None, limit=limits[limit_label])
        st.caption(f"พบ {found:,} SO (ทั้งหมด {total_all:,}) — แสดง {len(orders):,} รายการ")
        if not orders:
            st.warning("ไม่พบ SO ที่ตรงกับคำค้น")
        else:
            event = st.dataframe(
                order_table(orders),
                width="stretch",
                hide_index=True,
                on_select="rerun",
                selection_mode=TABLE_CLICK_MODES,
                key=f"_so_table_{hash(tuple(o['id'] for o in orders))}",
            )
            row, is_new = picked_row(event, "_so_table_pick")
            if row is not None and row < len(orders):
                if is_new:
                    _so_dialog(orders[row]["id"])
                if st.button(f"เปิด SO {orders[row]['so_number']} อีกครั้ง"):
                    _so_dialog(orders[row]["id"])

if can_edit:
    # ── นำเข้า ───────────────────────────────────────────────────────────
    with tabs[1]:
        st.markdown(
            "**1 แถว = 1 รายการสินค้า** — แถวที่มีเลขที่ SO เดียวกันจะรวมเป็น SO เดียว "
            "(ข้อมูลหัว SO เช่นวันที่ ผู้ซื้อ ผู้รับ ใส่ซ้ำทุกแถว) "
            "รองรับไฟล์จากแม่แบบด้านล่าง และไฟล์ที่ export จาก NAV ที่ใช้ชื่อคอลัมน์ภาษาอังกฤษ "
            "(เช่น Document No., Sell-to Customer Name, Ship-to Phone No.)"
        )
        st.download_button(
            "ดาวน์โหลดแม่แบบ Excel",
            data=sales_orders.template_bytes(),
            file_name="smartvoice_so_template.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            icon=":material/download:",
        )
        st.caption(
            f"ใส่เลขที่ SO ในทุกแถวสินค้า {sales_orders.SO_NUMBER_HELP} "
            "วันที่ใช้วัน/เดือน/ปี เช่น 25/11/2569 หรือ 25/11/2026 "
            "ยอดเงินที่ระบุจะใช้ตามไฟล์ ช่องว่างจะคำนวณเมื่อมีข้อมูลเพียงพอ"
        )
        st.warning(
            "หากเลขที่ SO ตรงกับใบเดิม การยืนยันนำเข้าจะเขียนข้อมูลหัวใบใหม่ตามไฟล์และแทนที่รายการสินค้าทั้งหมด "
            "ให้ใส่ทุกรายการที่ต้องการเก็บไว้ หากใบเดิมถูกซ่อน ระบบจะกู้คืนและอัปเดตใบนั้นด้วย"
        )

        upload_key = f"_so_upload_{st.session_state.get('_so_upload_n', 0)}"
        uploaded = st.file_uploader("เลือกไฟล์ .xlsx หรือ .csv", type=["xlsx", "csv"], help="เลือกไฟล์ตามแม่แบบ แล้วตรวจตัวอย่างก่อนยืนยันนำเข้า", key=upload_key)
        if uploaded is not None:
            try:
                frame = sales_orders.read_upload(uploaded.name, uploaded.getvalue())
            except ValueError as exc:
                st.error(f"เปิดไฟล์นำเข้าไม่ได้ — {exc} กรุณาตรวจว่าไฟล์เปิดได้และมีข้อมูล แล้วเลือกไฟล์อีกครั้ง")
                frame = None
            if frame is not None:
                result = sales_orders.parse_import(frame)
                if result.unknown_columns:
                    st.info("คอลัมน์ที่ระบบไม่รู้จักและจะข้ามไป: " + ", ".join(result.unknown_columns))
                for warning in result.warnings[:10]:
                    st.warning(warning)
                if result.errors:
                    st.error(
                        f"พบปัญหา {len(result.errors)} จุด — แก้ไฟล์แล้วอัปโหลดใหม่:\n\n"
                        + "\n".join(f"- {e}" for e in result.errors[:20])
                        + ("\n- …" if len(result.errors) > 20 else "")
                    )
                if result.orders:
                    preview = []
                    for header, lines in result.orders:
                        exists = db.get_sales_order(so_number=header["so_number"], include_deleted=True)
                        customer_id = sales_orders.find_customer_id(header)
                        status = "ใหม่"
                        if exists:
                            status = "กู้คืนและอัปเดตใบที่ซ่อน" if exists.get("deleted_at") else "อัปเดตใบเดิม"
                            customer_id = customer_id or exists.get("customer_id")
                        customer = db.get_customer_by_id(customer_id) if customer_id else None
                        preview.append({
                            "เลขที่ SO": header["so_number"],
                            "สถานะ": status,
                            "วันที่สั่งซื้อ": labels.thai_time(header.get("order_date") or header.get("document_date"), with_time=False),
                            "ผู้ซื้อ": header.get("sell_to_name") or "-",
                            "ผู้รับ": header.get("ship_to_name") or "-",
                            "รายการ": len(lines),
                            "ยอดรวมสุทธิ": labels.baht(header.get("grand_total")),
                            "จับคู่ลูกค้า": f"{customer['first_name']} {customer['last_name']}" if customer else "-",
                        })
                    st.markdown(f"**ตรวจสอบก่อนนำเข้า: {len(result.orders):,} SO, {result.line_count:,} รายการสินค้า**")
                    st.caption("ตรวจสถานะ จำนวนสินค้า และลูกค้าก่อนยืนยัน ระบบเทียบเบอร์ผู้รับก่อน แล้วจึงลองเบอร์ผู้ซื้อ หากไม่พบจะคงการผูกลูกค้าเดิม")
                    st.dataframe(pd.DataFrame(preview), width="stretch", hide_index=True)
                    if st.button(
                        f"นำเข้า {len(result.orders):,} SO", type="primary",
                        disabled=bool(result.errors), icon=":material/upload:",
                    ):
                        summary = sales_orders.import_orders(
                            result.orders, actor=user, actor_role=role, source=uploaded.name
                        )
                        st.session_state["_so_upload_n"] = st.session_state.get("_so_upload_n", 0) + 1
                        _flash(
                            "success",
                            f"นำเข้าแล้ว — เพิ่มใหม่ {summary['created']} SO, อัปเดต {summary['updated']} SO, "
                            f"{summary['lines']} รายการสินค้า, ผูกกับลูกค้าในระบบ {summary['linked']} SO",
                        )
                        st.rerun()
                elif not result.errors:
                    st.warning("ไม่พบข้อมูล SO ในไฟล์")

    # ── เพิ่ม/แก้ไข ──────────────────────────────────────────────────────
    with tabs[2]:
        mode = st.radio("วิธีบันทึกใบสั่งขาย", ["เพิ่ม SO ใหม่", "แก้ไข SO ที่มีอยู่"], horizontal=True, key="_so_mode")
        order = None
        if mode == "แก้ไข SO ที่มีอยู่":
            pick_search = st.text_input("ค้นหา SO ที่จะแก้ไข", key="_so_edit_search",
                                        placeholder="เลขที่ SO, ชื่อ หรือเบอร์")
            candidates = db.list_sales_orders(search=pick_search or None, limit=50)
            if not candidates:
                st.info("ไม่พบ SO")
            else:
                picked_id = st.selectbox(
                    "เลือก SO", [o["id"] for o in candidates], key="_so_edit_pick",
                    format_func=lambda i: next(
                        f"{o['so_number']} — {o.get('sell_to_name') or o.get('ship_to_name') or '-'}"
                        for o in candidates if o["id"] == i
                    ),
                )
                order = db.get_sales_order(so_id=picked_id)

        if mode == "เพิ่ม SO ใหม่" or order:
            sid = order["id"] if order else "new"
            values = order or {}

            def _text(key: str, label: str, col, **kw):
                return col.text_input(label, value=values.get(key) or "", key=f"_so_{key}_{sid}", **kw)

            def _date(key: str, label: str, col):
                raw = values.get(key)
                return col.date_input(label, value=date.fromisoformat(raw) if raw else None,
                                      format="DD/MM/YYYY", key=f"_so_{key}_{sid}")

            def _money(key: str, label: str, col, help_text=None):
                return col.number_input(label, value=values.get(key), min_value=None, step=100.0,
                                        format="%.2f", key=f"_so_{key}_{sid}", help=help_text)

            header = {}
            st.markdown("**ข้อมูลเอกสาร**")
            st.caption("ต้องระบุเลขที่ SO ช่องอื่นกรอกตามใบสั่งขายหรือเว้นว่างได้")
            c1, c2, c3 = st.columns(3)
            header["so_number"] = _text(
                "so_number", "เลขที่ SO *", c1, disabled=bool(order), placeholder="เช่น SO-001",
                help=sales_orders.SO_NUMBER_HELP,
            )
            c1.caption(f"เลขที่ SO ของใบใหม่ต้องไม่ซ้ำ {sales_orders.SO_NUMBER_HELP} เมื่อบันทึกแล้วเปลี่ยนเลขเดิมไม่ได้")
            header["document_date"] = _date("document_date", "วันที่เอกสาร", c2)
            c2.caption("เลือกวัน/เดือน/ปี ค.ศ. เช่น 25/11/2026")
            header["order_date"] = _date("order_date", "วันที่สั่งซื้อ", c3)
            c1, c2, c3 = st.columns(3)
            header["shipment_date"] = _date("shipment_date", "วันที่จัดส่ง", c1)
            header["promised_delivery_date"] = _date("promised_delivery_date", "วันที่สัญญาส่ง", c2)
            header["due_date"] = _date("due_date", "วันครบกำหนด", c3)
            c1, c2, c3, c4 = st.columns(4)
            header["sales_type"] = _text("sales_type", "ประเภทการขาย", c1, placeholder="เช่น ขายปลีก")
            header["purchasing_type"] = _text("purchasing_type", "ประเภทการซื้อ", c2, placeholder="เช่น สั่งซื้อตามใบเสนอราคา")
            header["salesperson"] = _text("salesperson", "พนักงานขาย", c3, placeholder="เช่น SALE-01")
            header["currency"] = _text("currency", "สกุลเงิน", c4, placeholder="เช่น THB")
            c1, c2, c3 = st.columns(3)
            header["external_doc"] = _text("external_doc", "เลขที่เอกสารภายนอก", c1, placeholder="เช่น EXT-015")
            c1.caption("เลขอ้างอิงบนเอกสารภายนอกที่เกี่ยวกับการขายครั้งนี้")
            header["credit_term"] = _text("credit_term", "เงื่อนไขการชำระเงิน", c2, placeholder="เช่น เครดิต 30 วัน")
            header["customer_po_no"] = _text("customer_po_no", "เลขที่ใบสั่งซื้อของลูกค้า (PO)", c3, placeholder="เช่น PO-075")
            c3.caption("คัดลอกเลขจากใบสั่งซื้อที่ลูกค้าออกให้")

            buyer_col, receiver_col = st.columns(2)
            with buyer_col:
                st.markdown("**ผู้ซื้อ (Sell-to)**")
                st.caption("ระบุบุคคลหรือบริษัทที่สั่งซื้อ เช่น บริษัทที่ออกใบ PO")
                header["sell_to_no"] = _text("sell_to_no", "รหัสผู้ซื้อ", st, placeholder="เช่น C-001")
                header["sell_to_name"] = _text("sell_to_name", "ชื่อผู้ซื้อ", st, placeholder="เช่น บริษัท ตัวอย่าง จำกัด")
                header["sell_to_address"] = _text("sell_to_address", "ที่อยู่ผู้ซื้อ", st, placeholder="เช่น 12 ถนนสีลม กรุงเทพฯ")
                header["sell_to_contact"] = _text("sell_to_contact", "ผู้ติดต่อ", st, placeholder="เช่น คุณมาลี")
                header["sell_to_phone"] = _text("sell_to_phone", "เบอร์ผู้ซื้อ", st, placeholder="เช่น 0812345678")
            with receiver_col:
                st.markdown("**ผู้รับ / ที่อยู่จัดส่ง (Ship-to)**")
                st.caption("ระบุผู้รับสินค้าที่ปลายทางและที่อยู่จัดส่ง เช่น สาขาหรือผู้รับที่ลูกค้าแจ้งไว้")
                header["ship_to_name"] = _text("ship_to_name", "ชื่อผู้รับ", st, placeholder="เช่น คุณสมชาย")
                header["ship_to_address"] = _text("ship_to_address", "ที่อยู่ผู้รับ", st, placeholder="เช่น 45 ถนนสาทร กรุงเทพฯ")
                header["ship_to_contact"] = _text("ship_to_contact", "ผู้ติดต่อ", st, placeholder="เช่น คุณนิด")
                header["ship_to_phone"] = _text("ship_to_phone", "เบอร์ผู้รับ", st, placeholder="เช่น 0812345678")
                header["ship_to_email"] = _text("ship_to_email", "อีเมลผู้รับ", st, placeholder="เช่น receiver@example.com")

            customers = db.get_all_customers()
            options = [None] + [c["id"] for c in customers]
            names = {c["id"]: _customer_label(c) for c in customers}
            current = values.get("customer_id")
            header["customer_id"] = st.selectbox(
                "ลูกค้าในระบบ",
                options,
                index=options.index(current) if current in options else 0,
                format_func=lambda cid: "อัตโนมัติจากเบอร์ผู้รับ/ผู้ซื้อ" if cid is None else names.get(cid, str(cid)),
                key=f"_so_customer_{sid}",
            )
            st.caption("เลือกชื่อลูกค้าเองได้ หากเลือกอัตโนมัติ ระบบจะค้นจากเบอร์ผู้รับก่อน แล้วลองเบอร์ผู้ซื้อ "
                       "ถ้าไม่พบ ใบใหม่จะยังไม่ผูกลูกค้า ส่วนใบเดิมจะคงลูกค้าที่ผูกไว้")

            st.markdown("**รายการสินค้า**")
            st.caption(
                "เลื่อนตารางในแนวนอนเพื่อดูคอลัมน์ด้านขวา กด + ใต้ตารางเพื่อเพิ่มสินค้า 1 รายการต่อแถว ใส่รหัสหรือบาร์โค้ดตามเอกสาร เช่น MAT-01 "
                "และคลังที่ระบุในใบสั่งขาย เช่น WH-01 ช่องจำนวนกรอกตามหน่วยสินค้า เช่น 2 ชิ้น"
            )
            st.caption(
                "กรอกราคาต่อ 1 หน่วยและส่วนลดรวมของแถวเป็นจำนวนเงินตามสกุลเงินของใบสั่งขาย "
                "หากเว้นจำนวนเงินรายการ ระบบคำนวณ จำนวน × ราคาต่อหน่วย − ส่วนลด เช่น 2 × 500 − 50 = 950 บาท"
            )
            line_frame = pd.DataFrame(
                [
                    {
                        **{k: ln.get(k) for k in ("line_no", "item_no", "description", "uom", "location",
                                                  "quantity", "unit_price", "discount", "amount")},
                        "requested_delivery_date": date.fromisoformat(ln["requested_delivery_date"])
                        if ln.get("requested_delivery_date") else None,
                    }
                    for ln in (values.get("lines") or [])
                ],
                columns=["line_no", "item_no", "description", "requested_delivery_date", "uom",
                         "location", "quantity", "unit_price", "discount", "amount"],
            )
            line_frame["requested_delivery_date"] = pd.to_datetime(line_frame["requested_delivery_date"]).dt.date
            for col in ("item_no", "description", "uom", "location"):
                # Blank, not a grey "None", in the editor; blanks are saved as NULL.
                line_frame[col] = line_frame[col].astype("object").where(line_frame[col].notna(), "")
            for col in ("line_no", "quantity", "unit_price", "discount", "amount"):
                line_frame[col] = pd.to_numeric(line_frame[col])
            edited = st.data_editor(
                line_frame,
                num_rows="dynamic",
                width="stretch",
                hide_index=True,
                key=f"_so_lines_{sid}",
                column_config={
                    "line_no": st.column_config.NumberColumn("ลำดับ", step=1),
                    "item_no": st.column_config.TextColumn("รหัสสินค้า/บาร์โค้ด"),
                    "description": st.column_config.TextColumn("รายละเอียดสินค้า", width="large"),
                    "requested_delivery_date": st.column_config.DateColumn("วันที่ต้องการรับ", format="DD/MM/YYYY"),
                    "uom": st.column_config.TextColumn("หน่วย", help="เช่น ชิ้น หรือชุด"),
                    "location": st.column_config.TextColumn("คลังสินค้า"),
                    "quantity": st.column_config.NumberColumn("จำนวน"),
                    "unit_price": st.column_config.NumberColumn("ราคาต่อหน่วย", format="%.2f"),
                    "discount": st.column_config.NumberColumn("ส่วนลด", format="%.2f", help=sales_orders.FIELDS_BY_KEY["line_discount"].note),
                    "amount": st.column_config.NumberColumn("จำนวนเงิน", format="%.2f", help=sales_orders.FIELDS_BY_KEY["amount"].note),
                },
            )

            st.markdown("**ยอดเงิน**")
            st.caption(
                "ระบบรวมจำนวนเงินทุกรายการ หักส่วนลดท้ายบิล แล้วบวก VAT "
                "กรอกส่วนลดและ VAT เป็นจำนวนเงินตามเอกสาร เช่น ยอดรายการรวม 950 บาท หักส่วนลดท้ายบิล 50 บาท "
                "หากเอกสารระบุ VAT 63 บาท ให้กรอก 63 ยอดรวมสุทธิจะเป็น 963 บาท ช่องเหล่านี้ไม่รับอัตราเปอร์เซ็นต์"
            )
            auto_totals = st.checkbox(
                "คำนวณยอดรวม / ยอดหลังหักส่วนลด / ยอดรวมสุทธิ จากรายการสินค้าอัตโนมัติ",
                value=sales_orders.totals_follow_lines(order) if order else True,
                key=f"_so_auto_totals_{sid}",
            )
            if auto_totals:
                c1, c2 = st.columns(2)
                header["discount"] = _money("discount", "ส่วนลดท้ายบิล", c1)
                header["vat"] = _money("vat", "ภาษีมูลค่าเพิ่ม (จำนวนเงิน)", c2)
            else:
                c1, c2, c3, c4, c5 = st.columns(5)
                header["total"] = _money("total", "ยอดรวม", c1)
                header["discount"] = _money("discount", "ส่วนลดท้ายบิล", c2)
                header["net_amount"] = _money("net_amount", "ยอดหลังหักส่วนลด", c3)
                header["vat"] = _money("vat", "ภาษีมูลค่าเพิ่ม (จำนวนเงิน)", c4)
                header["grand_total"] = _money("grand_total", "ยอดรวมสุทธิ", c5)
            preview_lines, line_errors = sales_orders.clean_lines(edited.to_dict("records"))
            if not line_errors:
                totals = header.copy()
                sales_orders.complete_totals(totals, preview_lines)
                st.markdown(f"**ยอดสุทธิก่อนบันทึก** {labels.baht(totals.get('grand_total'))} {header.get('currency') or ''}")
            st.markdown("**หมายเหตุ**")
            header["remark"] = st.text_area("ข้อความเพิ่มเติม", placeholder="เช่น โทรแจ้งผู้รับก่อนจัดส่ง", value=values.get("remark") or "", key=f"_so_remark_{sid}")

            if st.button("บันทึก SO", type="primary", key=f"_so_save_{sid}", icon=":material/save:", use_container_width=True):
                saved_id, error = sales_orders.save_manual(
                    header, edited.to_dict("records"), actor=user, actor_role=role,
                    so_id=order["id"] if order else None,
                )
                if error:
                    st.error(error)
                else:
                    _flash("success", f"บันทึก SO {header['so_number'].strip()} แล้ว")
                    if not order:
                        # Fresh form for the next SO.
                        for key in [k for k in st.session_state if str(k).endswith("_new") and str(k).startswith("_so_")]:
                            del st.session_state[key]
                    st.rerun()

    # ── ที่ซ่อนไว้ ───────────────────────────────────────────────────────
    with tabs[3]:
        hidden = db.get_deleted_sales_orders()
        if not hidden:
            st.info("ไม่มี SO ที่ถูกซ่อนไว้")
        for h in hidden:
            info_col, btn_col = st.columns([4, 1])
            info_col.markdown(
                f"**{h['so_number']}** — {h.get('sell_to_name') or h.get('ship_to_name') or '-'}  \n"
                f"ซ่อนโดย {h.get('deleted_by') or '-'} เมื่อ {labels.thai_time(h.get('deleted_at'))}"
            )
            if btn_col.button("กู้คืน", key=f"_so_restore_{h['id']}", width="stretch"):
                error = sales_orders.restore(h["id"], actor=user, actor_role=role)
                _flash("error" if error else "success", error or f"กู้คืน SO {h['so_number']} แล้ว")
                st.rerun()
