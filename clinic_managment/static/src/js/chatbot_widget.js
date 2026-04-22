/** @odoo-module **/
import { Component, useState, useRef, onMounted, onPatched, markup } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const WELCOME_TEXT = [
    "Hello! I'm your Clinic Assistant 👋\n\n",
    "Use the menu below or just type freely.\n\n",
    "**Quick actions:**\n",
    "• Book an appointment\n",
    "• View patient records\n",
    "• Check doctor availability\n",
    "• Open any record directly\n\n",
    "**Navigation examples:**\n",
    "• \"show appointments\"\n",
    "• \"open patient PAT001\"\n",
    "• \"open appointment APP0039\"\n",
    "• \"open doctor Ayush\"",
].join("");

const PAGE_ROUTES = {
    appointments:  { model: "clinic.appointment",  view_mode: "list,form", name: "Appointments" },
    patients:      { model: "clinic.patient",       view_mode: "list,form", name: "Patients" },
    doctors:       { model: "clinic.doctor",        view_mode: "list,form", name: "Doctors" },
    consultations: { model: "clinic.consultation",  view_mode: "list,form", name: "Consultations" },
};

const VIEWS = {
    CHAT: "chat", MENU: "menu",
    BOOK_DOCTOR: "book_doctor", BOOK_DATE: "book_date",
    BOOK_TIME: "book_time", BOOK_PATIENT: "book_patient",
    BOOK_NOTES: "book_notes", BOOK_CONFIRM: "book_confirm",
    RECORDS_TYPE: "records_type", AVAIL_DOCTOR: "avail_doctor",
    AVAIL_DATE: "avail_date", NAV: "nav", OPEN_TYPE: "open_type",
};

const SpeechRecognitionClass =
    window.SpeechRecognition || window.webkitSpeechRecognition || null;

function getDateChips() {
    const chips = [], now = new Date();
    const days   = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];
    const months = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"];
    for (let i = 0; i < 10; i++) {
        const d = new Date(now);
        d.setDate(now.getDate() + i);
        chips.push({
            label: i === 0 ? "Today" : i === 1 ? "Tmrw" : days[d.getDay()],
            num:   d.getDate(),
            month: months[d.getMonth()],
            value: d.toISOString().slice(0, 10),
        });
    }
    return chips;
}

function getTimeSlots() {
    const slots = { morning: [], afternoon: [], evening: [] };
    for (let h = 8; h < 20; h++) {
        for (let m = 0; m < 60; m += 30) {
            const label = `${h % 12 || 12}:${m === 0 ? "00" : "30"} ${h < 12 ? "AM" : "PM"}`;
            const value = `${String(h).padStart(2,"0")}:${m === 0 ? "00" : "30"}`;
            const slot  = { label, value };
            if      (h < 12) slots.morning.push(slot);
            else if (h < 17) slots.afternoon.push(slot);
            else             slots.evening.push(slot);
        }
    }
    return slots;
}

function normCode(s) { return s.replace(/[\\/\-\s]/g, "").toUpperCase(); }

class ClinicChatbot extends Component {
    static template = "clinic_managment.ClinicChatbot";
    static props    = {};

    setup() {
        this.state = useState({
            open: false, view: VIEWS.MENU, message: "", loading: false, listening: false,
            messages: [{ role: "assistant", text: WELCOME_TEXT }],
            doctors: [], doctorsLoading: false,
            booking: {
                doctor: null, date: "", dateLabel: "",
                time: "", timeLabel: "", patientCode: "", notes: "",
            },
            bookedSlots: [], slotsLoading: false,
            recordsType: "patient", recordsInput: "",
            availDoctor: null, availDate: "",
            openType: "patient", openInput: "",
            breadcrumbs: [],
            streamingText: "",
            isStreaming:   false,
        });

        this.action      = useService("action");
        this.history     = [];
        this.dateChips   = getDateChips();
        this.timeSlots   = getTimeSlots();
        this.messagesRef = useRef("messages");
        this.currentRec  = null;

        onMounted(() => { this._scrollToBottom(); this._loadDoctors(); });
        onPatched(() => this._scrollToBottom());
    }

    get tz() { return Intl.DateTimeFormat().resolvedOptions().timeZone; }

    get safeBookingDoctor() {
        return this.state.booking.doctor ||
               { name: "", speciality: "", fees: "0", is_available: false };
    }

    async _post(url, body) {
        const res = await fetch(url, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    async _loadDoctors() {
        this.state.doctorsLoading = true;
        try {
            const data = await this._post("/api/v19/chatbot/doctors", {});
            this.state.doctors = data.result?.doctors ?? data.doctors ?? [];
        } catch (e) {
            console.error("loadDoctors:", e);
            this.state.doctors = [];
        } finally {
            this.state.doctorsLoading = false;
        }
    }

    async _loadBookedSlots() {
        if (!this.state.booking.doctor || !this.state.booking.date) return;
        this.state.slotsLoading = true;
        try {
            const data = await this._post("/api/v19/chatbot/booked_slots", {
                doctor_id: this.state.booking.doctor.id,
                date:      this.state.booking.date,
                tz_name:   this.tz,
            });
            this.state.bookedSlots = data.booked ?? [];
        } catch (e) {
            this.state.bookedSlots = [];
        } finally {
            this.state.slotsLoading = false;
        }
    }

    // ── Navigation ────────────────────────────────────────────────────────────
    _goTo(view, crumbLabel) {
        if (crumbLabel) {
            this.state.breadcrumbs = [
                ...this.state.breadcrumbs,
                { label: crumbLabel, view: this.state.view },
            ];
        }
        this.state.view = view;
    }

    _goBack() {
        const crumbs = this.state.breadcrumbs;
        if (!crumbs.length) { this.state.view = VIEWS.MENU; return; }
        const last = crumbs[crumbs.length - 1];
        this.state.breadcrumbs = crumbs.slice(0, -1);
        this.state.view = last.view;
    }

    _goHome() {
        this.state.view        = VIEWS.MENU;
        this.state.breadcrumbs = [];
        this._resetBooking();
    }

    _resetBooking() {
        this.state.booking = {
            doctor: null, date: "", dateLabel: "",
            time: "", timeLabel: "", patientCode: "", notes: "",
        };
        this.state.bookedSlots = [];
    }

    toggleChat() {
        this.state.open = !this.state.open;
        if (this.state.open && !this.state.doctors.length) this._loadDoctors();
    }

    clearChat() {
        this.history             = [];
        this.state.messages      = [{ role: "assistant", text: WELCOME_TEXT }];
        this.state.streamingText = "";
        this.state.isStreaming   = false;
        this._goHome();
    }

    onInputChange(ev)        { this.state.message              = ev.target.value; }
    onCodeChange(ev)         { this.state.booking.patientCode  = ev.target.value.toUpperCase(); }
    onNotesChange(ev)        { this.state.booking.notes        = ev.target.value; }
    onRecordsInputChange(ev) { this.state.recordsInput         = ev.target.value; }
    onOpenInputChange(ev)    { this.state.openInput            = ev.target.value; }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    // ── Voice Input ───────────────────────────────────────────────────────────
    toggleVoice() {
        if (!SpeechRecognitionClass) {
            alert("Voice input is not supported in this browser. Please use Chrome or Edge.");
            return;
        }
        if (this.state.listening) {
            if (this.currentRec) { this.currentRec.stop(); }
            this.state.listening = false; this.currentRec = null; return;
        }
        const rec      = new SpeechRecognitionClass();
        rec.continuous = false; rec.interimResults = false;
        rec.lang       = "en-US"; rec.maxAlternatives = 1;
        rec.onresult   = (ev) => {
            this.state.message   = ev.results[0][0].transcript;
            this.state.listening = false; this.currentRec = null;
            this.sendMessage();
        };
        rec.onerror = rec.onend = () => { this.state.listening = false; this.currentRec = null; };
        this.currentRec = rec; this.state.listening = true; rec.start();
    }

    isSlotBooked(value) { return this.state.bookedSlots.includes(value); }

    _pushAssistant(text) {
        this.state.messages = [...this.state.messages, { role: "assistant", text }];
    }
    _pushUser(text) {
        this.state.messages = [...this.state.messages, { role: "user", text }];
    }

    // ── BOOKING FLOW (GUI) ────────────────────────────────────────────────────
    openBookFlow() { this._resetBooking(); this._goTo(VIEWS.BOOK_DOCTOR, "Menu"); }

    selectDoctor(doc) {
        if (!doc.is_available) return;
        this.state.booking.doctor = doc;
        this._goTo(VIEWS.BOOK_DATE, "Book");
    }

    selectDate(chip) {
        this.state.booking.date      = chip.value;
        this.state.booking.dateLabel = `${chip.label} ${chip.num} ${chip.month}`;
        this.state.booking.time      = "";
        this._goTo(VIEWS.BOOK_TIME, chip.label);
        this._loadBookedSlots();
    }

    selectTime(slot) {
        if (this.isSlotBooked(slot.value)) return;
        this.state.booking.time      = slot.value;
        this.state.booking.timeLabel = slot.label;
        this._goTo(VIEWS.BOOK_PATIENT, this.state.booking.timeLabel);
    }

    goToNotes() {
        const code = normCode(this.state.booking.patientCode);
        if (!code) { alert("Please enter a patient code."); return; }
        this.state.booking.patientCode = code;
        this._goTo(VIEWS.BOOK_NOTES, `Patient: ${code}`);
    }

    skipNotes()   { this.state.booking.notes = ""; this._goTo(VIEWS.BOOK_CONFIRM, "Notes"); }
    goToConfirm() { this._goTo(VIEWS.BOOK_CONFIRM, "Notes"); }

    get bookingDatetime() {
        const b = this.state.booking;
        return `${b.date} ${b.time}:00`;
    }

    async confirmBooking() {
        const b = this.state.booking;
        if (!b.doctor || !b.date || !b.time || !b.patientCode) return;
        this.state.loading = true;
        try {
            const data = await this._post("/api/v19/chatbot/message", {
                direct_booking: {
                    patient_code:         b.patientCode,
                    doctor_name:          b.doctor.name,
                    appointment_datetime: this.bookingDatetime,
                    notes:                b.notes,
                },
                tz_name: this.tz,
            });
            const d           = data?.data ?? {};
            const reply       = d.reply       ?? "Booking failed.";
            const action      = d.action      ?? null;
            const action_data = d.action_data ?? {};
            this._pushAssistant(reply);
            this.history.push({ role: "assistant", content: reply });
            this._resetBooking();
            this._goTo(VIEWS.CHAT, "Confirm");
            if (action) {
                setTimeout(() => this._handleAction(action, action_data), 1400);
            }
        } catch (e) {
            this._pushAssistant("❌ Booking failed. Please try again.");
            this._goTo(VIEWS.CHAT, "Confirm");
        } finally {
            this.state.loading = false;
        }
    }

    // ── RECORDS FLOW ──────────────────────────────────────────────────────────
    openRecordsFlow() { this.state.recordsInput = ""; this._goTo(VIEWS.RECORDS_TYPE, "Menu"); }
    setRecordsType(t) { this.state.recordsType = t; }

    async fetchRecords() {
        const inp = this.state.recordsInput.trim();
        if (!inp) { alert("Please enter a patient code or doctor name."); return; }
        this.state.loading = true;
        this._goTo(VIEWS.CHAT, "Records");
        try {
            const data = await this._post("/api/v19/chatbot/records", {
                type: this.state.recordsType, identifier: inp, tz_name: this.tz,
            });
            this._pushAssistant(data.reply ?? "No records found.");
        } catch (e) {
            this._pushAssistant("❌ Error fetching records. Please try again.");
        } finally {
            this.state.loading = false;
        }
    }

    // ── AVAILABILITY FLOW ─────────────────────────────────────────────────────
    openAvailFlow() {
        this.state.availDoctor = null; this.state.availDate = "";
        this._goTo(VIEWS.AVAIL_DOCTOR, "Menu");
    }
    selectAvailDoctor(doc) { this.state.availDoctor = doc; this._goTo(VIEWS.AVAIL_DATE, doc.name); }

    async checkAvail(date) {
        const doc = this.state.availDoctor;
        if (!doc) return;
        this.state.loading = true;
        this._goTo(VIEWS.CHAT, "Availability");
        try {
            const data = await this._post("/api/v19/chatbot/availability", {
                doctor_name: doc.name, date: date || "", tz_name: this.tz,
            });
            this._pushAssistant(data.reply ?? "No availability info.");
        } catch (e) {
            this._pushAssistant("❌ Error checking availability.");
        } finally {
            this.state.loading = false;
        }
    }

    // ── NAV FLOW ──────────────────────────────────────────────────────────────
    openNavFlow() { this._goTo(VIEWS.NAV, "Menu"); }
    doNavigate(page) { this._navigateTo(page); }

    // ── OPEN RECORD FLOW ──────────────────────────────────────────────────────
    openOpenFlow() { this.state.openInput = ""; this._goTo(VIEWS.OPEN_TYPE, "Menu"); }
    setOpenType(t) { this.state.openType  = t; }

    async doOpenRecord() {
        const inp = this.state.openInput.trim();
        if (!inp) { alert("Please enter a code or name."); return; }
        this.state.loading = true;
        this._goTo(VIEWS.CHAT, "Open Record");
        try {
            const data = await this._post("/api/v19/chatbot/open_record", {
                type: this.state.openType, identifier: inp,
            });
            this._pushAssistant(data.reply ?? "Record not found.");
            if (data.action) {
                setTimeout(() => this._handleAction(data.action, data.action_data || {}), 800);
            }
        } catch (e) {
            this._pushAssistant("❌ Error opening record.");
        } finally {
            this.state.loading = false;
        }
    }

    // ── Core navigation helpers ───────────────────────────────────────────────

    /**
     * Navigate to a module list view.
     * Closes chatbot first, then fires doAction.
     */
    _navigateTo(page) {
        const route = PAGE_ROUTES[page];
        if (!route) {
            console.warn("Unknown page:", page);
            return;
        }
        this.state.open = false;
        this.action.doAction({
            type:      "ir.actions.act_window",
            name:      route.name,
            res_model: route.model,
            view_mode: route.view_mode,
            views:     route.view_mode.split(",").map(v => [false, v.trim()]),
            target:    "current",
        });
    }

    /**
     * Open a single record in form view.
     * ── FIX: res_id is cast to integer so Odoo accepts it correctly.
     * ── FIX: views array uses the standard [false, "form"] tuple format.
     * ── FIX: chatbot is closed BEFORE doAction so the navigation fires cleanly.
     */
    _openRecord(model, recordId) {
        const id = parseInt(recordId, 10);
        if (!model || !id) {
            console.error("_openRecord: invalid model or id", model, recordId);
            return;
        }
        // Close chatbot panel first so the form view has full screen
        this.state.open = false;
        this.action.doAction({
            type:      "ir.actions.act_window",
            res_model: model,
            res_id:    id,
            view_mode: "form",
            views:     [[false, "form"]],
            target:    "current",
        });
    }

    /**
     * Unified action handler — single entry point for ALL server actions.
     * Called from: _sendStreaming, confirmBooking, doOpenRecord.
     *
     * Supported actions:
     *   open_appointment  → { appointment_id }
     *   open_record       → { model, record_id }
     *   navigate          → { page }
     */
    _handleAction(action, action_data) {
        if (!action) return;

        if (action === "open_appointment" && action_data?.appointment_id) {
            this._openRecord("clinic.appointment", action_data.appointment_id);
        } else if (action === "open_record" && action_data?.model && action_data?.record_id) {
            this._openRecord(action_data.model, action_data.record_id);
        } else if (action === "navigate" && action_data?.page) {
            this._navigateTo(action_data.page);
        }
    }

    // ── Free-text chat ────────────────────────────────────────────────────────
    async sendMessage() {
        const text = this.state.message.trim();
        if (!text || this.state.loading) return;

        this._pushUser(text);
        this.history.push({ role: "user", content: text });
        this.state.message = "";
        this.state.loading = true;

        if (this.state.view !== VIEWS.CHAT) this._goTo(VIEWS.CHAT, "");

        try {
            await this._sendStreaming(text);
        } catch (err) {
            console.error("sendMessage error:", err);
            this._pushAssistant("⚠️ Connection error. Make sure Ollama is running and try again.");
        } finally {
            this.state.loading       = false;
            this.state.isStreaming   = false;
            this.state.streamingText = "";
        }
    }

    async _sendStreaming(text) {
        const historyForServer = this.history.map(m => ({ role: m.role, content: m.content }));

        let res;
        try {
            res = await fetch("/api/v19/chatbot/stream", {
                method:  "POST",
                headers: { "Content-Type": "application/json" },
                body:    JSON.stringify({
                    message: text, history: historyForServer, tz_name: this.tz,
                }),
            });
        } catch (e) {
            this._pushAssistant("⚠️ Cannot reach server. Please try again.");
            return;
        }

        if (!res.ok || !res.body) {
            this._pushAssistant("⚠️ Server error. Please try again.");
            return;
        }

        this.state.isStreaming   = true;
        this.state.streamingText = "";

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();
        let fullText    = "";
        let action      = null;
        let action_data = {};
        let store_msg   = null;

        try {
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const lines = decoder.decode(value, { stream: true }).split("\n");
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const dataStr = line.slice(6).trim();
                    if (dataStr === "[DONE]") break;
                    try {
                        const parsed = JSON.parse(dataStr);
                        if (parsed.token      !== undefined) {
                            fullText += parsed.token;
                            this.state.streamingText = fullText;
                        }
                        if (parsed.action      !== undefined) action      = parsed.action;
                        if (parsed.action_data !== undefined) action_data = parsed.action_data;
                        if (parsed.store_msg   !== undefined) store_msg   = parsed.store_msg;
                    } catch {
                        fullText += dataStr;
                        this.state.streamingText = fullText;
                    }
                }
            }
        } catch (e) {
            // show whatever arrived
        } finally {
            reader.cancel().catch(() => {});
        }

        const finalText = fullText || this.state.streamingText;
        this.state.isStreaming   = false;
        this.state.streamingText = "";

        if (finalText) this._pushAssistant(finalText);

        const histContent = store_msg !== null ? store_msg : (finalText || "");
        this.history.push({ role: "assistant", content: histContent });

        // ── FIX: give the DOM one frame to render the reply before navigating
        if (action) {
            setTimeout(() => this._handleAction(action, action_data), 900);
        }
    }

    _scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) el.scrollTop = el.scrollHeight;
    }

    formatText(raw) {
        const html = String(raw)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");
        return markup(html);
    }

    get isMenu()        { return this.state.view === VIEWS.MENU; }
    get isChat()        { return this.state.view === VIEWS.CHAT; }
    get isBookDoctor()  { return this.state.view === VIEWS.BOOK_DOCTOR; }
    get isBookDate()    { return this.state.view === VIEWS.BOOK_DATE; }
    get isBookTime()    { return this.state.view === VIEWS.BOOK_TIME; }
    get isBookPatient() { return this.state.view === VIEWS.BOOK_PATIENT; }
    get isBookNotes()   { return this.state.view === VIEWS.BOOK_NOTES; }
    get isBookConfirm() { return this.state.view === VIEWS.BOOK_CONFIRM; }
    get isRecordsType() { return this.state.view === VIEWS.RECORDS_TYPE; }
    get isAvailDoctor() { return this.state.view === VIEWS.AVAIL_DOCTOR; }
    get isAvailDate()   { return this.state.view === VIEWS.AVAIL_DATE; }
    get isNav()         { return this.state.view === VIEWS.NAV; }
    get isOpenType()    { return this.state.view === VIEWS.OPEN_TYPE; }
    get showBreadcrumb(){ return this.state.breadcrumbs.length > 0; }
}

registry.category("systray").add("clinic_chatbot", {
    Component: ClinicChatbot,
}, { sequence: 1 });

export { ClinicChatbot };